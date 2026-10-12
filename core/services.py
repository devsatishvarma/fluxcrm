"""Transactional identity and company-profile operations."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from identity.models import AuthThrottle, CompanySettings, Role, User

LOGIN_LIMIT = 5
LOGIN_WINDOW = timedelta(minutes=15)
RESET_LIMIT = 5
RESET_WINDOW = timedelta(hours=1)


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
        if stored.get("version") != 1:
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
        "display_name": user.display_name,
        "timezone": user.timezone,
        "is_active": user.is_active,
        "role": user.role.key,
        "manager_id": user.manager_id,
    }


def setup_first_administrator(*, profile, admin_user, password, request_id=""):
    try:
        with transaction.atomic():
            if User.objects.exists() or CompanySettings.objects.exists():
                raise SetupAlreadyCompleted
            validate_password(password)
            admin_role, _ = ensure_roles()
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
    from core.policy import require_action

    require_action(actor, "user", "A")
    if invite and request is None:
        raise ValidationError("An invitation requires an HTTP request.")
    if not invite:
        validate_password(password, user=User(username=user_data["username"]))
    _, standard_role = ensure_roles()
    role = user_data.get("role") or standard_role
    user = User(
        username=user_data["username"],
        email=user_data["email"],
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
    from core.policy import require_action

    require_action(actor, "user", "A")
    if not user.is_active:
        raise ValidationError("Enable this user before sending a password reset.")
    form = PasswordResetForm({"email": user.email})
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


@transaction.atomic
def set_user_active(*, actor, user, active, request_id=""):
    from core.policy import require_action

    require_action(actor, "user", "A")
    if user.pk == actor.pk and not active:
        raise ValidationError("You cannot disable your own account.")
    if (
        not active
        and user.is_company_admin
        and not User.objects.filter(role__key="ADMIN", is_active=True)
        .exclude(pk=user.pk)
        .exists()
    ):
        raise ValidationError("The last active administrator cannot be disabled.")
    before = user_snapshot(user)
    user.is_active = active
    user.save(update_fields=("is_active",))
    record_audit(
        actor=actor,
        action="user.activated" if active else "user.disabled",
        instance=user,
        before=before,
        after=user_snapshot(user),
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
    limit = LOGIN_LIMIT if scope == "login" else RESET_LIMIT
    window = LOGIN_WINDOW if scope == "login" else RESET_WINDOW
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


def set_user_manager(*, actor, user, manager, request_id=""):
    from core.policy import require_action

    require_action(actor, "user", "A")
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
    members = User.objects.filter(pk__in=member_ids)
    team.members.set(members)
    record_audit(
        actor=actor,
        action="team.created" if creating else "team.updated",
        instance=team,
        before=before,
        after=_team_snapshot(team),
        request_id=request_id,
    )
    return team


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
    from django.db.models import Q

    from core.access import scoped
    from core.policy import allows, grant_for, model_for, owner_ids_for

    if not allows(user, "audit", "R"):
        return AuditEvent.objects.none()
    queryset = AuditEvent.objects.select_related("actor")
    grant = grant_for(user, "audit")
    if grant.scope == "ALL":
        return queryset
    allowed = owner_ids_for(user, grant.scope) or set()
    query = Q(actor_id__in=allowed) | Q(
        object_type="identity.user",
        object_id__in=[str(pk) for pk in allowed],
    )
    for key in ("lead", "account", "contact", "deal", "activity", "task"):
        model = model_for(key)
        visible = [
            str(pk)
            for pk in scoped(model.objects.all(), user).values_list("pk", flat=True)
        ]
        if visible:
            query |= Q(object_type=model._meta.label_lower, object_id__in=visible)
    return queryset.filter(query).distinct()


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
    from core.policy import require_action

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
