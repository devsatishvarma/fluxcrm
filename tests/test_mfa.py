"""Phase 10B TOTP multi-factor authentication."""

import re
import time
from unittest.mock import patch

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from audit.models import AuditEvent
from core.mfa import confirm_totp_enrollment, start_totp_enrollment
from core.services import ensure_roles
from identity.models import Role, User

pytestmark = pytest.mark.django_db

ADMIN_PASSWORD = "correct-horse-battery"


class _Clock:
    def __init__(self):
        self.now = time.time()

    def time(self):
        return self.now

    def advance(self, seconds=30):
        self.now += seconds


@pytest.fixture
def totp_clock():
    clock = _Clock()
    with (
        patch("django_otp.oath.time", clock.time),
        patch("django_otp.plugins.otp_totp.models.time.time", clock.time),
    ):
        yield clock


def setup_payload(**overrides):
    payload = {
        "legal_name": "Infoshare Systems Inc.",
        "display_name": "Infoshare Systems",
        "street": "26040 Acero",
        "city": "Mission Viejo",
        "region": "CA",
        "postal_code": "92691",
        "country": "US",
        "industry": "Information Technology",
        "offered_services": "IT Consulting",
        "base_currency": "USD",
        "fiscal_year_start_month": 1,
        "default_timezone": "America/Los_Angeles",
        "admin_username": "satish",
        "admin_email": "satish@example.test",
        "admin_display_name": "Satish",
        "password": ADMIN_PASSWORD,
        "password_confirmation": ADMIN_PASSWORD,
    }
    payload.update(overrides)
    return payload


def complete_setup(client):
    return client.post(reverse("core:setup"), setup_payload())


def current_totp(device: TOTPDevice) -> str:
    return f"{totp(device.bin_key):06d}"


def enroll_user(user, client=None, clock=None):
    from django.contrib.sessions.backends.db import SessionStore

    enrollment = start_totp_enrollment(user=user)
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user
    request.session = client.session if client is not None else SessionStore()
    confirm_totp_enrollment(
        user=user,
        token=current_totp(enrollment["device"]),
        request=request,
    )
    if clock is not None:
        clock.advance(30)
    return TOTPDevice.objects.get(user=user, confirmed=True)


def login_with_mfa(client, username, password, clock=None):
    client.post(reverse("core:login"), {"username": username, "password": password})
    device = TOTPDevice.objects.get(user__username=username, confirmed=True)
    if clock is not None:
        clock.advance(30)
        device.refresh_from_db()
    return client.post(reverse("core:mfa_verify"), {"token": current_totp(device)})


def reset_mfa_throttle(user):
    for model in (TOTPDevice, StaticDevice):
        for device in model.objects.filter(user=user):
            device.throttle_reset()


@pytest.fixture
def mfa_on(settings):
    settings.MFA_REQUIRED = True


def test_password_alone_is_insufficient_when_mfa_required(client, mfa_on):
    complete_setup(client)
    response = client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 302
    assert response.url == reverse("core:mfa_enroll")
    blocked = client.get(reverse("core:home"))
    assert blocked.status_code == 302
    assert blocked.url == reverse("core:mfa_enroll")


def test_enroll_verify_and_backup_code_flow(client, mfa_on, totp_clock):
    complete_setup(client)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    enroll_page = client.get(reverse("core:mfa_enroll"))
    assert enroll_page.status_code == 200
    assert b"Authenticator QR code" in enroll_page.content
    device = TOTPDevice.objects.get(user__username="satish", confirmed=False)
    confirmed = client.post(
        reverse("core:mfa_enroll"),
        {"token": current_totp(device)},
    )
    assert confirmed.status_code == 302
    assert confirmed.url == reverse("core:mfa_backup_codes")
    assert AuditEvent.objects.filter(action="user.mfa_enrolled").exists()
    codes_page = client.get(reverse("core:mfa_backup_codes"))
    assert codes_page.status_code == 200
    codes = re.findall(rb"<code>([^<]+)</code>", codes_page.content)
    assert len(codes) == 10
    assert client.get(reverse("core:home")).status_code == 200

    client.post(reverse("core:logout"))
    totp_clock.advance(30)
    login_again = client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    assert login_again.url == reverse("core:mfa_verify")
    home_blocked = client.get(reverse("core:home"))
    assert home_blocked.status_code == 302
    assert home_blocked.url == reverse("core:mfa_verify")
    device = TOTPDevice.objects.get(user__username="satish", confirmed=True)
    bad = client.post(reverse("core:mfa_verify"), {"token": "000000"})
    assert bad.status_code == 200
    assert b"not valid" in bad.content
    reset_mfa_throttle(User.objects.get(username="satish"))
    totp_clock.advance(30)
    device.refresh_from_db()
    good = client.post(
        reverse("core:mfa_verify"),
        {"token": current_totp(device)},
    )
    assert good.status_code == 302
    assert client.get(reverse("core:home")).status_code == 200

    client.post(reverse("core:logout"))
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    from django_otp.plugins.otp_static.models import StaticToken

    backup = StaticToken.objects.filter(
        device__user__username="satish",
        device__name="backup",
    ).values_list("token", flat=True).first()
    assert backup is not None
    assert backup.encode() in codes
    reset_mfa_throttle(User.objects.get(username="satish"))
    used = client.post(reverse("core:mfa_verify"), {"token": backup})
    assert used.status_code == 302
    client.post(reverse("core:logout"))
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    reused = client.post(reverse("core:mfa_verify"), {"token": backup})
    assert reused.status_code == 200
    assert b"not valid" in reused.content


def test_admin_cannot_clear_mfa_super_admin_can(client, mfa_on, totp_clock):
    complete_setup(client)
    ensure_roles()
    satish = User.objects.get(username="satish")
    enroll_user(satish, client=client, clock=totp_clock)
    login_with_mfa(client, "satish", ADMIN_PASSWORD, clock=totp_clock)

    target = User.objects.create_user(
        username="riley",
        email="riley@example.test",
        password="another-strong-pass",
        display_name="Riley",
        role=Role.objects.get(key="STANDARD_USER"),
    )
    enroll_user(target, clock=totp_clock)

    admin = User.objects.create_user(
        username="ada",
        email="ada@example.test",
        password="another-strong-pass",
        display_name="Ada",
        role=Role.objects.get(key="ADMIN"),
    )
    enroll_user(admin, clock=totp_clock)
    guest = Client()
    login_with_mfa(guest, "ada", "another-strong-pass", clock=totp_clock)
    denied = guest.post(reverse("core:user_clear_mfa", args=[target.pk]))
    assert denied.status_code == 403

    cleared = client.post(reverse("core:user_clear_mfa", args=[target.pk]))
    assert cleared.status_code == 302
    assert not TOTPDevice.objects.filter(user=target, confirmed=True).exists()
    assert AuditEvent.objects.filter(
        action="user.mfa_cleared", object_id=str(target.pk)
    ).exists()


def test_help_documents_mfa(client, settings):
    settings.MFA_REQUIRED = False
    complete_setup(client)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    help_page = client.get(reverse("core:help"))
    assert help_page.status_code == 200
    assert b"authenticator app (TOTP)" in help_page.content
    assert b"clears MFA" in help_page.content


def test_mfa_verify_is_application_throttled(client, mfa_on, totp_clock):
    complete_setup(client)
    satish = User.objects.get(username="satish")
    enroll_user(satish, client=client, clock=totp_clock)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    reset_mfa_throttle(satish)
    for _ in range(5):
        bad = client.post(reverse("core:mfa_verify"), {"token": "000000"})
        assert bad.status_code == 200
    blocked = client.post(reverse("core:mfa_verify"), {"token": "000000"})
    assert blocked.status_code == 429
    assert b"Too many attempts" in blocked.content
