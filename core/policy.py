"""Versioned object, action, and scope rules.

The architecture matrix is the seed. An administrator can edit a role's
grants; ``grants_version`` records that change. Standard User stays the
Phase 1 own-records role beside the matrix.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

OBJECTS = (
    "lead",
    "account",
    "contact",
    "deal",
    "activity",
    "task",
    "report",
    "import",
    "user",
    "settings",
    "audit",
)
ACTIONS = "CRUDXA"
SCOPES = ("NONE", "OWN", "TEAM", "REPORTING_LINE", "ALL")
SCOPE_CHOICES = ("OWN", "TEAM", "REPORTING_LINE", "ALL")
OBJECT_LABELS = {
    "leads.lead": "lead",
    "accounts.account": "account",
    "accounts.contact": "contact",
    "sales.deal": "deal",
    "activities.activity": "activity",
    "activities.task": "task",
}
_denials: ContextVar[list | None] = ContextVar("glidecrm_access_denials", default=None)


class AccessDenied(PermissionDenied):
    """A grant or scope refusal. The denial log stores no CRM field values."""

    def __init__(self, object_key, action, object_id=""):
        self.object_key = object_key
        self.action = action
        self.object_id = str(object_id or "")
        super().__init__("You do not have access to this record.")


@dataclass(frozen=True)
class Grant:
    """Actions this role may take, each with its own scope."""

    scopes: dict
    create: str = ""

    @property
    def actions(self):
        return frozenset(self.scopes)

    def scope_for(self, action):
        return self.scopes.get(action, "NONE")

    @property
    def scope(self):
        """Read scope. Write checks use scope_for."""
        return self.scope_for("R")


def _grant(actions, scope, create=""):
    entry = {"scopes": {letter: scope for letter in actions}}
    if create:
        entry["create"] = create
    return entry


def _scopes(scopes, create=""):
    entry = {"scopes": {letter: scope for letter, scope in scopes.items()}}
    if create:
        entry["create"] = create
    return entry


def _matrix(objects):
    return {"version": 2, "objects": objects}


_CRM = (
    "lead",
    "account",
    "contact",
    "deal",
    "activity",
    "task",
)
_ACCOUNT_SALES = _scopes({"C": "OWN", "R": "ALL", "U": "OWN", "D": "OWN"})
_ACCOUNT_MANAGER = _scopes(
    {"C": "REPORTING_LINE", "R": "ALL", "U": "REPORTING_LINE", "X": "REPORTING_LINE"}
)
_ACCOUNT_SUCCESS = _scopes({"C": "OWN", "R": "ALL", "U": "OWN"})


ROLE_SPECS = {
    "SUPER_ADMIN": {
        "name": "Super Admin",
        "description": "Creates users, sets passwords, and can change every record.",
        "scope_policy": "ALL",
        "permissions": _matrix(
            {key: _grant("CRUDXA", "ALL") for key in _CRM}
            | {
                "report": _grant("RXA", "ALL"),
                "import": _grant("CRXA", "ALL"),
                "user": _grant("RUDA", "ALL"),
                "settings": _grant("A", "ALL"),
                "audit": _grant("R", "ALL"),
            }
        ),
    },
    "ADMIN": {
        "name": "Admin",
        "description": "Teams, settings, and grants. Cannot add users or passwords.",
        "scope_policy": "ALL",
        "permissions": _matrix(
            {key: _grant("CRUDXA", "ALL") for key in _CRM}
            | {
                "report": _grant("RXA", "ALL"),
                "import": _grant("CRXA", "ALL"),
                "user": _grant("RUDA", "ALL"),
                "settings": _grant("A", "ALL"),
                "audit": _grant("R", "ALL"),
            }
        ),
    },
    "STANDARD_USER": {
        "name": "Standard User",
        "description": "Day-to-day access to records this person owns.",
        "scope_policy": "OWN",
        "permissions": _matrix(
            {
                "lead": _grant("CRUD", "OWN"),
                "deal": _grant("CRUD", "OWN", create="sql_conversion"),
                "activity": _grant("CRUD", "OWN"),
                "task": _grant("CRUD", "OWN"),
                "account": _ACCOUNT_SALES,
                "contact": _ACCOUNT_SALES,
                "report": _grant("R", "OWN"),
                "import": _grant("", "NONE"),
                "user": _grant("", "NONE"),
                "settings": _grant("", "NONE"),
                "audit": _grant("R", "OWN"),
            }
        ),
    },
    "SALES_DIRECTOR": {
        "name": "Sales Director/Manager",
        "description": "Own records plus the reporting line. Can import.",
        "scope_policy": "REPORTING_LINE",
        "permissions": _matrix(
            {
                "lead": _grant("CRUX", "REPORTING_LINE"),
                "deal": _grant("CRUX", "REPORTING_LINE", create="sql_conversion"),
                "activity": _grant("CRUX", "REPORTING_LINE"),
                "task": _grant("CRUX", "REPORTING_LINE"),
                "account": _ACCOUNT_MANAGER,
                "contact": _ACCOUNT_MANAGER,
                "report": _grant("RX", "REPORTING_LINE"),
                "import": _grant("CRX", "REPORTING_LINE"),
                "user": _grant("R", "REPORTING_LINE"),
                "settings": _grant("", "NONE"),
                "audit": _grant("R", "OWN"),
            }
        ),
    },
    "SALES_EXECUTIVE": {
        "name": "Sales Executive",
        "description": "Own leads, deals, tasks, and activities.",
        "scope_policy": "OWN",
        "permissions": _matrix(
            {
                "lead": _grant("CRU", "OWN"),
                "deal": _grant("CRU", "OWN", create="sql_conversion"),
                "activity": _grant("CRU", "OWN"),
                "task": _grant("CRU", "OWN"),
                "account": _scopes({"C": "OWN", "R": "ALL", "U": "OWN"}),
                "contact": _scopes({"C": "OWN", "R": "ALL", "U": "OWN"}),
                "report": _grant("R", "OWN"),
                "import": _grant("", "NONE"),
                "user": _grant("", "NONE"),
                "settings": _grant("", "NONE"),
                "audit": _grant("R", "OWN"),
            }
        ),
    },
    "MARKETING": {
        "name": "Marketing",
        "description": "Team leads and activities. Edit these grants from Roles.",
        "scope_policy": "TEAM",
        "permissions": _matrix(
            {
                "lead": _grant("CRU", "TEAM"),
                "account": _grant("R", "ALL"),
                "contact": _grant("R", "ALL"),
                "deal": _grant("R", "TEAM"),
                "activity": _grant("CRU", "TEAM"),
                "task": _grant("CRU", "TEAM"),
                "report": _grant("R", "TEAM"),
                "import": _grant("", "NONE"),
                "user": _grant("", "NONE"),
                "settings": _grant("", "NONE"),
                "audit": _grant("R", "OWN"),
            }
        ),
    },
    "CLIENT_SUCCESS": {
        "name": "Client Success",
        "description": "Accounts and contacts. An administrator can edit these grants.",
        "scope_policy": "TEAM",
        "permissions": _matrix(
            {
                "lead": _grant("R", "TEAM"),
                "account": _ACCOUNT_SUCCESS,
                "contact": _ACCOUNT_SUCCESS,
                "deal": _grant("R", "TEAM"),
                "activity": _grant("CRU", "TEAM"),
                "task": _grant("CRU", "TEAM"),
                "report": _grant("R", "TEAM"),
                "import": _grant("", "NONE"),
                "user": _grant("", "NONE"),
                "settings": _grant("", "NONE"),
                "audit": _grant("R", "OWN"),
            }
        ),
    },
    "READ_ONLY": {
        "name": "Read-only/Executive",
        "description": "Company-wide read. No changes and no export.",
        "scope_policy": "ALL",
        "permissions": _matrix(
            {
                key: _grant("R", "ALL")
                for key in (
                    "lead",
                    "account",
                    "contact",
                    "deal",
                    "activity",
                    "task",
                    "report",
                )
            }
            | {
                "audit": _grant("R", "OWN"),
                "import": _grant("", "NONE"),
                "user": _grant("", "NONE"),
                "settings": _grant("", "NONE"),
            }
        ),
    },
}


def object_key_for(model):
    return OBJECT_LABELS.get(model._meta.label_lower)


def model_for(object_key):
    from accounts.models import Account, Contact
    from activities.models import Activity, Task
    from leads.models import Lead
    from sales.models import Deal

    return {
        "lead": Lead,
        "account": Account,
        "contact": Contact,
        "deal": Deal,
        "activity": Activity,
        "task": Task,
    }[object_key]


def _normalize_scope(scope):
    if scope == "MANAGER_TREE":
        return "REPORTING_LINE"
    if scope not in SCOPES:
        return "OWN"
    return scope


def grant_for(user, object_key):
    role = getattr(user, "role", None)
    if role is None or object_key not in OBJECTS:
        return Grant({}, "")
    stored = role.permissions or {}
    if stored.get("version") not in {1, 2}:
        stored = ROLE_SPECS.get(role.key, {}).get("permissions", {})
    raw = (stored.get("objects") or {}).get(object_key) or {}
    if "scopes" in raw:
        scopes = {}
        for action, scope in (raw.get("scopes") or {}).items():
            if action in ACTIONS:
                scopes[action] = _normalize_scope(scope)
        return Grant(scopes, raw.get("create") or "")
    scope = _normalize_scope(raw.get("scope") or "OWN")
    return Grant(
        {letter: scope for letter in (raw.get("actions") or "") if letter in ACTIONS},
        raw.get("create") or "",
    )


def allows(user, object_key, action, *, lead=None):
    if not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False):
        return False
    grant = grant_for(user, object_key)
    if action == "C" and object_key == "deal" and lead is not None:
        permitted = action in grant.actions or grant.create == "sql_conversion"
        return permitted and getattr(lead, "stage", "") == "SQL"
    return action in grant.actions


def can_correct(user):
    """Stage correction and probability override."""
    role = getattr(user, "role", None)
    return role is not None and role.key in {"SUPER_ADMIN", "ADMIN", "SALES_DIRECTOR"}


def write_scope(user, object_key):
    """Scope used when choosing an owner. Update, then create, then assign."""
    grant = grant_for(user, object_key)
    for action in ("U", "C", "A"):
        scope = grant.scope_for(action)
        if scope != "NONE":
            return scope
    return "NONE"


def note_denial(*, actor, object_key, action, object_id="", reason):
    current = _denials.get()
    if current is None:
        current = []
        _denials.set(current)
    current.append(
        {
            "actor_id": getattr(actor, "pk", None),
            "object_key": object_key,
            "action": action,
            "object_id": str(object_id or ""),
            "reason": reason,
        }
    )


def deny(user, object_key, action, object_id="", reason="missing_grant"):
    note_denial(
        actor=user,
        object_key=object_key,
        action=action,
        object_id=object_id,
        reason=reason,
    )
    raise AccessDenied(object_key, action, object_id)


def require_action(user, object_key, action, *, lead=None, object_id=""):
    if allows(user, object_key, action, lead=lead):
        return
    deny(user, object_key, action, object_id=object_id, reason="missing_grant")


def begin_denial_scope():
    return _denials.set([])


def end_denial_scope(token):
    pending = list(_denials.get() or [])
    _denials.reset(token)
    return pending


def flush_denials(pending, request_id=""):
    if not pending:
        return
    from audit.models import AuditEvent

    for item in pending:
        AuditEvent.objects.create(
            actor_id=item["actor_id"],
            action="access.denied",
            object_type="access",
            object_id=(item["object_id"] or item["object_key"])[:64],
            before_json=None,
            after_json={
                "object_key": item["object_key"],
                "action": item["action"],
                "object_id": item["object_id"],
                "reason": item["reason"],
            },
            request_id=request_id or "",
            source="web",
        )
        logger.info(
            "Access denied",
            extra={
                "object_key": item["object_key"],
                "action": item["action"],
                "reason": item["reason"],
            },
        )


def descendant_ids(user):
    """Active and inactive reports, walking the whole line without cycles."""
    from identity.models import User

    seen = set()
    frontier = [user.pk]
    while frontier:
        children = User.objects.filter(manager_id__in=frontier).values_list(
            "pk", flat=True
        )
        frontier = []
        for pk in children:
            if pk == user.pk or pk in seen:
                continue
            seen.add(pk)
            frontier.append(pk)
    return seen


def team_member_ids(user):
    from identity.models import Team, User

    team_id = getattr(user, "team_id", None)
    if not team_id or not Team.objects.filter(pk=team_id, active=True).exists():
        return set()
    return set(User.objects.filter(team_id=team_id).values_list("pk", flat=True))


def owner_ids_for(user, scope):
    """User ids whose records this scope includes. None means every owner."""
    if scope == "MANAGER_TREE":
        scope = "REPORTING_LINE"
    if scope == "ALL":
        return None
    if not getattr(user, "is_authenticated", False) or scope == "NONE":
        return set()
    if scope == "OWN":
        return {user.pk}
    if scope == "TEAM":
        peers = team_member_ids(user)
        return peers or {user.pk}
    if scope == "REPORTING_LINE":
        return {user.pk, *descendant_ids(user)}
    return {user.pk}


def assignable_users(user, object_key):
    from identity.models import User

    queryset = User.objects.filter(is_active=True).order_by("display_name")
    allowed = owner_ids_for(user, write_scope(user, object_key))
    if allowed is None:
        return queryset
    return queryset.filter(pk__in=allowed)


def visible_user_ids(user):
    if allows(user, "user", "A"):
        return None
    if allows(user, "user", "R"):
        return owner_ids_for(user, grant_for(user, "user").scope)
    return set()
