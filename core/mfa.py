"""TOTP enrollment, verification, and Super Admin recovery (Phase 10B)."""

from __future__ import annotations

import base64
import io
import logging

import qrcode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django_otp import devices_for_user, user_has_device
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.services import record_audit

logger = logging.getLogger(__name__)

TOTP_DEVICE_NAME = "authenticator"
BACKUP_DEVICE_NAME = "backup"


def mfa_enabled() -> bool:
    return bool(getattr(settings, "MFA_REQUIRED", True))


def user_has_mfa(user) -> bool:
    return user_has_device(user, confirmed=True)


def user_is_mfa_verified(request) -> bool:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    if not mfa_enabled():
        return True
    return bool(getattr(user, "is_verified", lambda: False)())


def post_password_login_redirect(user) -> str:
    """Where to send the user after password authentication succeeds."""
    if not mfa_enabled():
        return "core:home"
    if user_has_mfa(user):
        return "core:mfa_verify"
    return "core:mfa_enroll"


def _qr_data_uri(config_url: str) -> str:
    image = qrcode.make(config_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@transaction.atomic
def start_totp_enrollment(*, user, request_id=""):
    """Create or replace an unconfirmed TOTP device and return QR material."""
    TOTPDevice.objects.filter(
        user=user, name=TOTP_DEVICE_NAME, confirmed=False
    ).delete()
    if user_has_mfa(user):
        raise ValidationError(
            "Authenticator is already enrolled. Ask a Super Admin to clear MFA "
            "before enrolling again."
        )
    device = TOTPDevice.objects.create(
        user=user,
        name=TOTP_DEVICE_NAME,
        confirmed=False,
    )
    return {
        "device": device,
        "config_url": device.config_url,
        "secret": _totp_secret_base32(device),
        "qr_data_uri": _qr_data_uri(device.config_url),
    }


def _totp_secret_base32(device: TOTPDevice) -> str:
    # django-otp stores the key; config_url already embeds it. Expose the
    # manual-entry secret from the OTP URI query when present.
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(device.config_url).query)
    secrets_list = query.get("secret") or []
    if secrets_list:
        return secrets_list[0]
    return device.key


@transaction.atomic
def confirm_totp_enrollment(*, user, token: str, request, request_id=""):
    device = (
        TOTPDevice.objects.select_for_update()
        .filter(user=user, name=TOTP_DEVICE_NAME, confirmed=False)
        .first()
    )
    if device is None:
        raise ValidationError("Start authenticator enrollment before confirming.")
    if not device.verify_token(token.strip()):
        raise ValidationError("That authenticator code is not valid. Try again.")
    device.confirmed = True
    device.save(update_fields=("confirmed",))
    backup_codes = _rotate_backup_codes(user)
    otp_login(request, device)
    record_audit(
        actor=user,
        action="user.mfa_enrolled",
        instance=user,
        before=None,
        after={"device": "totp", "backup_codes": len(backup_codes)},
        request_id=request_id,
    )
    logger.info(
        "MFA enrolled",
        extra={"outcome": "success", "user_id": user.pk},
    )
    return backup_codes


def verify_mfa_token(*, user, token: str, request, request_id=""):
    cleaned = (token or "").strip().replace(" ", "")
    if not cleaned:
        raise ValidationError("Enter the authenticator or backup code.")
    for device in devices_for_user(user, confirmed=True):
        if device.verify_token(cleaned):
            otp_login(request, device)
            record_audit(
                actor=user,
                action="user.mfa_verified",
                instance=user,
                before=None,
                after={"device": device.persistent_id},
                request_id=request_id,
            )
            logger.info(
                "MFA verified",
                extra={"outcome": "success", "user_id": user.pk},
            )
            return device
    raise ValidationError("That code is not valid. Try again.")


def _rotate_backup_codes(user) -> list[str]:
    count = int(getattr(settings, "MFA_BACKUP_CODE_COUNT", 10))
    StaticDevice.objects.filter(user=user, name=BACKUP_DEVICE_NAME).delete()
    device = StaticDevice.objects.create(
        user=user,
        name=BACKUP_DEVICE_NAME,
        confirmed=True,
    )
    codes: list[str] = []
    for _ in range(count):
        raw = StaticToken.random_token()
        StaticToken.objects.create(device=device, token=raw)
        codes.append(raw)
    return codes


@transaction.atomic
def clear_user_mfa(*, actor, user, request_id=""):
    from core.policy import deny

    if not getattr(actor, "is_super_admin", False):
        deny(actor, "user", "A")
    if actor.pk == user.pk and user_has_mfa(user):
        # Allow clearing own MFA only when another Super Admin path exists;
        # still permit self-clear so a Super Admin can re-enroll after recovery.
        pass
    had_mfa = user_has_mfa(user)
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
    if not had_mfa:
        raise ValidationError("This user has no authenticator enrolled.")
    record_audit(
        actor=actor,
        action="user.mfa_cleared",
        instance=user,
        before={"mfa": True},
        after={"mfa": False},
        request_id=request_id,
    )
    logger.info(
        "MFA cleared",
        extra={"outcome": "success", "user_id": user.pk, "actor_id": actor.pk},
    )


def mfa_status_for_users(user_ids):
    """Return {user_id: True} for users with a confirmed MFA device."""
    if not user_ids:
        return {}
    enrolled = set()
    for model in (TOTPDevice, StaticDevice):
        enrolled.update(
            model.objects.filter(user_id__in=user_ids, confirmed=True).values_list(
                "user_id", flat=True
            )
        )
    return {user_id: user_id in enrolled for user_id in user_ids}