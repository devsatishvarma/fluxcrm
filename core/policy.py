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
SCOPES = ("OWN", "TEAM", "MANAGER_TREE", "ALL")
OBJECT_LABELS = {
    "leads.lead": "lead",
    "accounts.account": "account",
    "accounts.contact": "contact",
    "sales.deal": "deal",
    "activities.activity": "activity",
    "activities.task": "task",
}
_denials: ContextVar[list | None] = ContextVar("fluxcrm_access_denials", default=None)


class AccessDenied(PermissionDenied):
    """A grant or scope refusal. The denial log stores no CRM field values."""

    def __init__(self, object_key, action, object_id=""):
        self.object_key = object_key
        self.action = action
        self.object_id = str(object_id or "")
        super().__init__("You do not have access to this record.")


@dataclass(frozen=True)
class Grant:
    actions: frozenset
    scope: str
    create: str = ""


def _grant(actions, scope, create=""):
    entry = {"actions": actions, "scope": scope}
    if create:
        entry["create"] = create
    return entry


def _matrix(objects):
    return {"version": 1, "objects": objects}


ROLE_SPECS = {
    "ADMIN": {
        "name": "Admin",
        "description": "Bootstrap and configuration access.",
        "scope_policy": "ALL",
        "permissions": _matrix(
            {
                key: _grant("CRUDXA", "ALL")
                for key in (
                    "lead",
                    "account",
                    "contact",
                    "deal",
                    "activity",
                    "task",
                )
            }
            | {
                "report": _grant("A", "ALL"),
                "import": _grant("A", "ALL"),
                "user": _grant("A", "ALL"),
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
                key: _grant("CRUD", "OWN")
                for key in (
                    "lead",
                    "account",
                    "contact",
                    "deal",
                    "activity",
                    "task",
                )
            }
            | {
                "report": _grant("R", "OWN"),
                "import": _grant("CR", "OWN"),
                "user": _grant("", "OWN"),
                "settings": _grant("", "OWN"),
                "audit": _grant("R", "OWN"),
            }
        ),
    },
    "SALES_DIRECTOR": {
        "name": "Sales Director/Manager",
        "description": "Records owned by this person and their reporting line.",
        "scope_policy": "MANAGER_TREE",
        "permissions": _matrix(
            {
                key: _grant("CRUX", "MANAGER_TREE")
                for key in (
                    "lead",
                    "account",
                    "contact",
                    "deal",
                    "activity",
                    "task",
                )
            }
            | {
                "report": _grant("RX", "MANAGER_TREE"),
                "import": _grant("CRX", "TEAM"),
                "user": _grant("R", "MANAGER_TREE"),
                "settings": _grant("", "MANAGER_TREE"),
                "audit": _grant("R", "MANAGER_TREE"),
            }
        ),
    },
    "ACCOUNT_EXECUTIVE": {
        "name": "Account Executive",
        "description": "Own leads, and team accounts, contacts, and deals.",
        "scope_policy": "TEAM",
        "permissions": _matrix(
            {
                "lead": _grant("CRU", "OWN"),
                "account": _grant("CRU", "TEAM"),
                "contact": _grant("CRU", "TEAM"),
                "deal": _grant("CRU", "TEAM"),
                "activity": _grant("CRU", "TEAM"),
                "task": _grant("CRU", "TEAM"),
                "report": _grant("R", "TEAM"),
                "import": _grant("CR", "OWN"),
                "user": _grant("", "OWN"),
                "settings": _grant("", "OWN"),
                "audit": _grant("R", "TEAM"),
            }
        ),
    },
    "SDR": {
        "name": "SDR/BDR",
        "description": "Own leads. Team reads. Deal create only from SQL.",
        "scope_policy": "TEAM",
        "permissions": _matrix(
            {
                "lead": _grant("CRU", "OWN"),
                "account": _grant("R", "TEAM"),
                "contact": _grant("CRU", "TEAM"),
                "deal": _grant("R", "TEAM", create="sql_conversion"),
                "activity": _grant("CRU", "TEAM"),
                "task": _grant("CRU", "TEAM"),
                "report": _grant("R", "TEAM"),
                "import": _grant("CR", "OWN"),
                "user": _grant("", "OWN"),
                "settings": _grant("", "OWN"),
                "audit": _grant("R", "TEAM"),
            }
        ),
    },
    "MARKETING": {
        "name": "Marketing",
        "description": "Team leads and activities, with read access elsewhere.",
        "scope_policy": "TEAM",
        "permissions": _matrix(
            {
                "lead": _grant("CRU", "TEAM"),
                "account": _grant("R", "TEAM"),
                "contact": _grant("R", "TEAM"),
                "deal": _grant("R", "TEAM"),
                "activity": _grant("CRU", "TEAM"),
                "task": _grant("CRU", "TEAM"),
                "report": _grant("R", "TEAM"),
                "import": _grant("CR", "TEAM"),
                "user": _grant("", "TEAM"),
                "settings": _grant("", "TEAM"),
                "audit": _grant("R", "TEAM"),
            }
        ),
    },
    "CLIENT_SUCCESS": {
        "name": "Client Success",
        "description": "Team accounts and contacts. No import.",
        "scope_policy": "TEAM",
        "permissions": _matrix(
            {
                "lead": _grant("R", "TEAM"),
                "account": _grant("CRU", "TEAM"),
                "contact": _grant("CRU", "TEAM"),
                "deal": _grant("R", "TEAM"),
                "activity": _grant("CRU", "TEAM"),
                "task": _grant("CRU", "TEAM"),
                "report": _grant("R", "TEAM"),
                "import": _grant("", "TEAM"),
                "user": _grant("", "TEAM"),
                "settings": _grant("", "TEAM"),
                "audit": _grant("R", "TEAM"),
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
                    "audit",
                )
            }
            | {
                "import": _grant("", "ALL"),
                "user": _grant("", "ALL"),
                "settings": _grant("", "ALL"),
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


def grant_for(user, object_key):
    role = getattr(user, "role", None)
    if role is None or object_key not in OBJECTS:
        return Grant(frozenset(), "OWN")
    stored = role.permissions or {}
    if stored.get("version") != 1:
        stored = ROLE_SPECS.get(role.key, {}).get("permissions", {})
    raw = (stored.get("objects") or {}).get(object_key) or {}
    scope = raw.get("scope") or "OWN"
    if scope not in SCOPES:
        scope = "OWN"
    return Grant(
        frozenset(raw.get("actions") or ""),
        scope,
        raw.get("create") or "",
    )


def allows(user, object_key, action, *, lead=None):
    if not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False):
        return False
    grant = grant_for(user, object_key)
    if action in grant.actions:
        return True
    return bool(
        action == "C"
        and object_key == "deal"
        and grant.create == "sql_conversion"
        and getattr(lead, "stage", "") == "SQL_READY"
    )


def can_correct(user):
    """Stage correction and probability override: Admin or Sales Director."""
    role = getattr(user, "role", None)
    return role is not None and role.key in {"ADMIN", "SALES_DIRECTOR"}


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
    from identity.models import User

    active_teams = user.teams.filter(active=True)
    if not active_teams.exists():
        return set()
    return set(
        User.objects.filter(teams__in=active_teams, teams__active=True).values_list(
            "pk", flat=True
        )
    )


def owner_ids_for(user, scope):
    """User ids whose records this scope includes. None means every owner."""
    if scope == "ALL":
        return None
    if not getattr(user, "is_authenticated", False):
        return set()
    if scope == "OWN":
        return {user.pk}
    if scope == "TEAM":
        peers = team_member_ids(user)
        return peers or {user.pk}
    if scope == "MANAGER_TREE":
        return {user.pk, *descendant_ids(user)}
    return {user.pk}


def assignable_users(user, object_key):
    from identity.models import User

    queryset = User.objects.filter(is_active=True).order_by("display_name")
    allowed = owner_ids_for(user, grant_for(user, object_key).scope)
    if allowed is None:
        return queryset
    return queryset.filter(pk__in=allowed)


def visible_user_ids(user):
    if allows(user, "user", "A"):
        return None
    if allows(user, "user", "R"):
        return owner_ids_for(user, grant_for(user, "user").scope)
    return set()
