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
    admin, _ = Role.objects.update_or_create(
        key="ADMIN",
        defaults={
            "name": "Admin",
            "description": "Bootstrap and configuration access.",
            "permissions": {"company_settings": ["A"], "users": ["A"]},
            "scope_policy": "ALL",
        },
    )
    standard, _ = Role.objects.update_or_create(
        key="STANDARD_USER",
        defaults={
            "name": "Standard User",
            "description": "Day-to-day access without configuration rights.",
            "permissions": {"company_settings": [], "users": []},
            "scope_policy": "OWN",
        },
    )
    return admin, standard


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
