"""Transactional identity and company-profile operations."""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from core.forms import GlidePasswordResetForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from audit.models import AuditEvent
from core.validation import clean_email, clean_phone
from identity.models import AuthThrottle, CompanySettings, Role, User

LOGIN_LIMIT = 5
LOGIN_WINDOW = timedelta(minutes=15)
RESET_LIMIT = 5
RESET_WINDOW = timedelta(hours=1)

logger = logging.getLogger(__name__)


class SetupAlreadyCompleted(Exception):
    """Raised when first-run setup is submitted after an administrator exists."""


def ensure_roles():
    from core.policy import ROLE_SPECS

    for key, spec in ROLE_SPECS.items():
        role, created = Role.objects.get_or_create(
            key=key,
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "permissions": spec["permissions"],
                "scope_policy": spec["scope_policy"],
                "grants_version": 1,
            },
        )
        if created:
            continue
        stored = role.permissions or {}
        if stored.get("version") != 2:
            role.name = spec["name"]
            role.description = spec["description"]
            role.permissions = spec["permissions"]
            role.scope_policy = spec["scope_policy"]
            role.grants_version = 1
            role.save()
    return (
        Role.objects.get(key="ADMIN"),
        Role.objects.get(key="STANDARD_USER"),
    )


def _flatten_audit(value, prefix=""):
    if isinstance(value, dict):
        flat = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten_audit(item, path))
        return flat
    if prefix:
        return {prefix: value}
    return {}


def _audit_text(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return ", ".join(_audit_text(item) for item in value)
    return str(value)


def changed_fields(before, after):
    """Fields whose stored values differ. Unchanged fields are omitted."""
    after_flat = _flatten_audit(after) if isinstance(after, dict) else {}
    before_flat = _flatten_audit(before) if isinstance(before, dict) else {}
    rows = []
    for path in sorted(set(before_flat) | set(after_flat)):
        old = before_flat.get(path)
        new = after_flat.get(path)
        if path in before_flat and path in after_flat and old == new:
            continue
        before_text = _audit_text(old) if path in before_flat else "—"
        after_text = _audit_text(new) if path in after_flat else "—"
        if before_text == after_text:
            continue
        label = path.replace("_", " ").replace(".", " ")
        rows.append(
            {
                "label": label[:1].upper() + label[1:] if label else path,
                "before": before_text,
                "after": after_text,
            }
        )
    return rows


def record_audit(*, actor, action, instance, before, after, request_id=""):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        before_json=before,
        after_json=after,
        request_id=request_id,
        source="web",
    )


def company_snapshot(company: CompanySettings) -> dict:
    return {
        "legal_name": company.legal_name,
        "display_name": company.display_name,
        "address": company.address,
        "industry": company.industry,
        "offered_services": company.offered_services,
        "base_currency": company.base_currency,
        "fiscal_year_start_month": company.fiscal_year_start_month,
        "default_timezone": company.default_timezone,
        "lead_stale_days": company.lead_stale_days,
        "deal_stale_days": company.deal_stale_days,
        "has_logo": bool(company.logo),
    }


def user_snapshot(user: User) -> dict:
    return {
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "is_active": user.is_active,
        "role": user.role.key,
        "manager_id": user.manager_id,
        "team_id": user.team_id,
    }


def setup_first_administrator(*, profile, admin_user, password, request_id=""):
    try:
        with transaction.atomic():
            if User.objects.exists() or CompanySettings.objects.exists():
                raise SetupAlreadyCompleted
            validate_password(password)
            ensure_roles()
            admin_role = Role.objects.get(key="SUPER_ADMIN")
            company = CompanySettings.objects.create(**profile)
            user = User(
                username=admin_user["username"],
                email=admin_user["email"],
                display_name=admin_user["display_name"],
                timezone=company.default_timezone,
                role=admin_role,
                is_staff=False,
                is_superuser=False,
            )
            user.set_password(password)
            user.full_clean()
            user.save()
            record_audit(
                actor=user,
                action="company_settings.created",
                instance=company,
                before=None,
                after=company_snapshot(company),
                request_id=request_id,
            )
            record_audit(
                actor=user,
                action="user.created",
                instance=user,
                before=None,
                after=user_snapshot(user),
                request_id=request_id,
            )
            return company, user
    except IntegrityError as exc:
        if User.objects.exists() or CompanySettings.objects.exists():
            raise SetupAlreadyCompleted from exc
        raise


@transaction.atomic
def update_company_settings(*, actor, company, changes, request_id=""):
    from core.policy import require_action

    require_action(actor, "settings", "A")
    before = company_snapshot(company)
    for field, value in changes.items():
        setattr(company, field, value)
    company.full_clean()
    company.save()
    record_audit(
        actor=actor,
        action="company_settings.updated",
        instance=company,
        before=before,
        after=company_snapshot(company),
        request_id=request_id,
    )
    return company


@transaction.atomic
def create_standard_user(
    *,
    actor,
    user_data,
    password=None,
    invite=False,
    request=None,
    request_id="",
):
    from core.policy import deny

    if not getattr(actor, "is_super_admin", False):
        deny(actor, "user", "C")
    if invite and not settings.PASSWORD_RESET_ENABLED:
        raise ValidationError(
            "Password reset email is off until an email provider is connected. "
            "Set a temporary password instead."
        )
    if invite and request is None:
        raise ValidationError("An invitation requires an HTTP request.")
    if not invite:
        validate_password(password, user=User(username=user_data["username"]))
    _, standard_role = ensure_roles()
    role = user_data.get("role") or standard_role
    user = User(
        username=user_data["username"],
        email=user_data["email"],
        phone=clean_phone(user_data.get("phone")),
        display_name=user_data["display_name"],
        timezone=user_data["timezone"],
        role=role,
        manager=user_data.get("manager"),
        is_staff=False,
        is_superuser=False,
    )
    user.set_password(secrets.token_urlsafe(48) if invite else password)
    user.full_clean()
    user.save()
    record_audit(
        actor=actor,
        action="user.created",
        instance=user,
        before=None,
        after=user_snapshot(user),
        request_id=request_id,
    )
    if invite:
        send_user_password_reset(
            actor=actor,
            user=user,
            request=request,
            action="user.invited",
            request_id=request_id,
        )
    return user


def send_user_password_reset(
    *,
    actor,
    user,
    request,
    action="user.password_reset_requested",
    request_id="",
):
    from core.policy import deny

    if not getattr(actor, "is_super_admin", False):
        deny(actor, "user", "A")
    if not settings.PASSWORD_RESET_ENABLED:
        raise ValidationError(
            "Password reset email is off until an email provider is connected."
        )
    if not user.is_active:
        raise ValidationError("Enable this user before sending a password reset.")
    form = GlidePasswordResetForm({"email": user.email})
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    form.save(
        request=request,
        use_https=request.is_secure(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        email_template_name="registration/password_reset_email.txt",
        subject_template_name="registration/password_reset_subject.txt",
    )
    record_audit(
        actor=actor,
        action=action,
        instance=user,
        before=None,
        after={"delivery": "email", "user_id": user.pk},
        request_id=request_id,
    )


def issue_on_screen_password_reset_link(
    *,
    actor,
    user,
    request,
    request_id="",
):
    """Build a single-use reset URL for a Super Admin to copy. Never email it."""
    from django.contrib.auth.tokens import default_token_generator
    from django.urls import reverse
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    from core.policy import deny

    if not getattr(actor, "is_super_admin", False):
        deny(actor, "user", "A")
    if not user.is_active:
        raise ValidationError("Enable this user before creating a password reset link.")
    throttle_subject = f"{actor.pk}:{user.pk}"
    if is_throttled("admin_password_reset", throttle_subject):
        raise ValidationError(
            "Too many password reset links for this user. Wait and try again."
        )
    record_attempt("admin_password_reset", throttle_subject)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse(
        "core:password_reset_confirm",
        kwargs={"uidb64": uid, "token": token},
    )
    public_base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if public_base:
        reset_url = f"{public_base}{path}"
    else:
        reset_url = request.build_absolute_uri(path)
    record_audit(
        actor=actor,
        action="user.password_reset_link_issued",
        instance=user,
        before=None,
        after={"delivery": "on_screen", "user_id": user.pk},
        request_id=request_id,
    )
    logger.info(
        "On-screen password reset link issued",
        extra={"outcome": "success", "user_id": user.pk},
    )
    return reset_url


@transaction.atomic
def set_user_password(*, actor, user, password, request_id=""):
    from core.policy import deny

    if not getattr(actor, "is_super_admin", False):
        deny(actor, "user", "A")
    validate_password(password, user=user)
    user.set_password(password)
    user.save(update_fields=("password", "team"))
    record_audit(
        actor=actor,
        action="user.password_set",
        instance=user,
        before=None,
        after={"password": "set"},
        request_id=request_id,
    )


def _owned_records(user):
    from accounts.models import Account, Contact
    from activities.models import Activity, Task
    from leads.models import Lead
    from sales.models import Deal

    return [
        model.objects.filter(owner=user)
        for model in (Lead, Account, Contact, Deal, Activity, Task)
    ]


@transaction.atomic
def set_user_active(*, actor, user, active, reassign_to=None, request_id=""):
    from core.policy import require_action

    require_action(actor, "user", "A")
    if user.role_id and user.role.key == "SUPER_ADMIN" and not actor.is_super_admin:
        raise ValidationError("Only a Super Admin can change a Super Admin.")
    if user.pk == actor.pk and not active:
        raise ValidationError("You cannot disable your own account.")
    if (
        not active
        and user.role_id
        and user.role.key == "SUPER_ADMIN"
        and not User.objects.filter(role__key="SUPER_ADMIN", is_active=True)
        .exclude(pk=user.pk)
        .exists()
    ):
        raise ValidationError("The last Super Admin cannot be disabled.")
    moved = 0
    if not active:
        owned = _owned_records(user)
        count = sum(queryset.count() for queryset in owned)
        if count:
            if (
                reassign_to is None
                or not reassign_to.is_active
                or reassign_to.pk == user.pk
            ):
                raise ValidationError(
                    "Choose an active person to receive this user's records."
                )
            for queryset in owned:
                moved += queryset.update(owner=reassign_to)
    before = user_snapshot(user)
    user.is_active = active
    user.save(update_fields=("is_active", "team"))
    after = user_snapshot(user)
    if not active:
        after["reassigned_count"] = moved
        if reassign_to is not None and moved:
            after["reassign_to_id"] = reassign_to.pk
    record_audit(
        actor=actor,
        action="user.activated" if active else "user.disabled",
        instance=user,
        before=before,
        after=after,
        request_id=request_id,
    )
    return user


def _subject_hash(scope: str, subject: str) -> str:
    material = f"{settings.SECRET_KEY}:{scope}:{subject.strip().lower()}".encode()
    return hashlib.sha256(material).hexdigest()


def record_attempt(scope: str, subject: str):
    AuthThrottle.objects.create(
        scope=scope,
        subject_hash=_subject_hash(scope, subject),
    )


def is_throttled(scope: str, subject: str) -> bool:
    if scope in {"login", "mfa_verify"}:
        limit, window = LOGIN_LIMIT, LOGIN_WINDOW
    else:
        limit, window = RESET_LIMIT, RESET_WINDOW
    cutoff = timezone.now() - window
    return (
        AuthThrottle.objects.filter(
            scope=scope,
            subject_hash=_subject_hash(scope, subject),
            attempted_at__gte=cutoff,
        ).count()
        >= limit
    )


def update_role_grants(*, actor, role, permissions, request_id=""):
    from core.policy import require_action

    require_action(actor, "settings", "A")
    before = {
        "grants_version": role.grants_version,
        "permissions": role.permissions,
    }
    role.permissions = permissions
    role.grants_version += 1
    role.save(update_fields=("permissions", "grants_version"))
    record_audit(
        actor=actor,
        action="role.grants_updated",
        instance=role,
        before=before,
        after={
            "grants_version": role.grants_version,
            "permissions": role.permissions,
        },
        request_id=request_id,
    )
    return role


@transaction.atomic
def update_user(
    *,
    actor,
    user,
    display_name,
    email,
    phone,
    role,
    manager,
    team,
    request_id="",
):
    from core.policy import require_action

    require_action(actor, "user", "A")
    if user.role_id and user.role.key == "SUPER_ADMIN" and not actor.is_super_admin:
        raise ValidationError("Only a Super Admin can change a Super Admin.")
    if role.key == "SUPER_ADMIN" and not actor.is_super_admin:
        raise ValidationError(
            {"role": "Only a Super Admin can assign the Super Admin role."}
        )
    if actor.pk == user.pk and role.key != user.role.key:
        raise ValidationError({"role": "You cannot change your own role."})
    name = str(display_name or "").strip()
    if not name:
        raise ValidationError({"display_name": "Enter a name."})
    address, _domain = clean_email(email)
    if not address:
        raise ValidationError({"email": "Enter an email address."})
    number = clean_phone(phone)
    if (
        user.is_active
        and user.role.key == "SUPER_ADMIN"
        and role.key != "SUPER_ADMIN"
        and not User.objects.filter(role__key="SUPER_ADMIN", is_active=True)
        .exclude(pk=user.pk)
        .exists()
    ):
        raise ValidationError({"role": "The last Super Admin must keep that role."})
    if role.key in {"ADMIN", "SUPER_ADMIN"}:
        team = None
    elif team is None:
        raise ValidationError({"team": "Choose a team."})
    before = user_snapshot(user)
    user.display_name = name
    user.email = address
    user.phone = number
    user.role = role
    user.manager = manager
    user.team = team
    user.full_clean()
    user.save(
        update_fields=("display_name", "email", "phone", "role", "manager", "team")
    )
    if team is None:
        user.teams.clear()
    else:
        user.teams.set([team])
    record_audit(
        actor=actor,
        action="user.updated",
        instance=user,
        before=before,
        after=user_snapshot(user),
        request_id=request_id,
    )
    return user


def set_user_manager(*, actor, user, manager, request_id=""):
    from core.policy import require_action

    require_action(actor, "user", "A")
    if user.role_id and user.role.key == "SUPER_ADMIN" and not actor.is_super_admin:
        raise ValidationError("Only a Super Admin can change a Super Admin.")
    before = user_snapshot(user)
    user.manager = manager
    user.full_clean()
    user.save(update_fields=("manager",))
    record_audit(
        actor=actor,
        action="user.manager_changed",
        instance=user,
        before=before,
        after=user_snapshot(user),
        request_id=request_id,
    )
    return user


def _team_snapshot(team):
    return {
        "name": team.name,
        "manager_id": team.manager_id,
        "active": team.active,
        "member_ids": sorted(team.members.values_list("pk", flat=True)),
    }


@transaction.atomic
def save_team(*, actor, team, name, manager, member_ids, active, request_id=""):
    from core.policy import require_action

    require_action(actor, "user", "A")
    creating = team.pk is None
    before = None if creating else _team_snapshot(team)
    team.name = name.strip()
    team.manager = manager
    team.active = active
    team.full_clean()
    team.save()
    members = User.objects.filter(pk__in=member_ids, is_active=True)
    if not creating:
        members = members | team.members.filter(is_active=False)
    team.members.set(members)
    for member in members:
        if member.role_id and member.role.key in {"ADMIN", "SUPER_ADMIN"}:
            continue
        member.team = team
        member.save(update_fields=("team",))
        member.teams.set([team])
    removed = list(
        User.objects.filter(team=team)
        .exclude(pk__in=members.values("pk"))
        .select_related("role")
    )
    blocked = [
        person.display_name
        for person in removed
        if not (person.role_id and person.role.key in {"ADMIN", "SUPER_ADMIN"})
    ]
    if blocked:
        names = ", ".join(blocked)
        raise ValidationError(
            f"Move these people to another team before removing them: {names}."
        )
    for member in removed:
        member.team = None
        member.save(update_fields=("team",))
    record_audit(
        actor=actor,
        action="team.created" if creating else "team.updated",
        instance=team,
        before=before,
        after=_team_snapshot(team),
        request_id=request_id,
    )
    return team


def team_people(team):
    """Users assigned to this team, including inactive people."""
    if team.pk is None:
        return User.objects.none()
    return (
        User.objects.filter(Q(team=team) | Q(teams=team))
        .distinct()
        .order_by("display_name")
    )


@transaction.atomic
def delete_team(*, actor, team, request_id=""):
    """Delete a team only after every member has moved to another team."""
    from core.policy import require_action

    require_action(actor, "user", "A")
    if team_people(team).exists():
        raise ValidationError(
            "Move every member to another team before deleting this team."
        )
    before = _team_snapshot(team)
    record_audit(
        actor=actor,
        action="team.deleted",
        instance=team,
        before=before,
        after=None,
        request_id=request_id,
    )
    team.delete()


def review_administrators(*, actor, request_id=""):
    from core.policy import require_action

    require_action(actor, "user", "A")
    admin_ids = list(
        User.objects.filter(role__key="ADMIN", is_active=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    AuditEvent.objects.create(
        actor=actor,
        action="administrators.reviewed",
        object_type="identity.user",
        object_id="administrators",
        before_json=None,
        after_json={"active_admin_ids": admin_ids},
        request_id=request_id,
        source="web",
    )
    return admin_ids


def visible_audit_events(user):
    """Admin and Super Admin see every action. Everyone else sees their own."""
    from core.policy import allows

    if not allows(user, "audit", "R"):
        return AuditEvent.objects.none()
    queryset = AuditEvent.objects.select_related("actor")
    if getattr(user, "is_company_admin", False):
        return queryset
    return queryset.filter(actor=user)


def request_export(*, actor, object_key, query="", request_id=""):
    from django.db.models import Q

    from core.access import scoped
    from core.policy import model_for, require_action

    searchable = {
        "lead": ("company_name", "last_name"),
        "account": ("name",),
        "contact": ("last_name", "email"),
        "deal": ("title",),
        "activity": ("subject",),
        "task": ("title",),
    }
    if object_key not in searchable:
        raise ValidationError({"object": "Choose a record type."})
    require_action(actor, object_key, "X")
    text = str(query or "").strip()[:100]
    rows = scoped(model_for(object_key).objects.all(), actor)
    if text:
        lookup = Q()
        for field in searchable[object_key]:
            lookup |= Q(**{f"{field}__icontains": text})
        rows = rows.filter(lookup)
    count = rows.count()
    AuditEvent.objects.create(
        actor=actor,
        action="export.requested",
        object_type=model_for(object_key)._meta.label_lower,
        object_id=object_key,
        before_json=None,
        after_json={"object_key": object_key, "q": text, "row_count": count},
        request_id=request_id,
        source="web",
    )
    return count


def authorize_import(*, actor, object_key, request_id=""):
    from core.policy import allows, require_action

    if not (allows(actor, "import", "C") or allows(actor, "import", "A")):
        require_action(actor, "import", "C")
    if object_key not in {"lead", "account", "contact", "deal"}:
        raise ValidationError({"object": "Choose a record type."})
    AuditEvent.objects.create(
        actor=actor,
        action="import.authorized",
        object_type="import",
        object_id=object_key,
        before_json=None,
        after_json={"object_key": object_key},
        request_id=request_id,
        source="web",
    )
