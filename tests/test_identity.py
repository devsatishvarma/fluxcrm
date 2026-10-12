import logging
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, override_settings
from django.urls import reverse

from audit.models import AuditEvent
from core.forms import SetupForm
from core.services import SetupAlreadyCompleted, ensure_roles, setup_first_administrator
from identity.models import CompanySettings, User

pytestmark = pytest.mark.django_db

ADMIN_PASSWORD = "correct-horse-battery"


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
        "offered_services": "IT Consulting\nManaged Services",
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


def test_setup_is_repeatable_and_has_no_default_password(client):
    assert User.objects.exists() is False
    first = complete_setup(client)
    assert first.status_code == 302
    assert first.url == reverse("core:login")
    company = CompanySettings.objects.get()
    assert company.legal_name == "Infoshare Systems Inc."
    assert company.base_currency == "USD"
    assert company.fiscal_year_start_month == 1
    assert company.default_timezone == "America/Los_Angeles"
    admin = User.objects.get(username="satish")
    assert admin.check_password(ADMIN_PASSWORD)
    assert admin.is_staff is False
    assert admin.is_superuser is False
    assert "password" not in str(
        AuditEvent.objects.values_list("after_json", flat=True)
    )

    second = complete_setup(client)
    assert second.status_code == 302
    admin.refresh_from_db()
    assert admin.check_password(ADMIN_PASSWORD)
    assert User.objects.count() == 1


def test_active_user_can_log_in_and_disabled_user_cannot(client):
    complete_setup(client)
    _, standard = ensure_roles()
    user = User.objects.create_user(
        username="riley",
        email="riley@example.test",
        password="another-strong-pass",
        display_name="Riley",
        role=standard,
    )
    assert (
        client.post(
            reverse("core:login"),
            {"username": "riley", "password": "another-strong-pass"},
        ).status_code
        == 302
    )
    client.post(reverse("core:logout"))
    user.is_active = False
    user.save(update_fields=("is_active",))
    denied = client.post(
        reverse("core:login"),
        {"username": "riley", "password": "another-strong-pass"},
    )
    assert denied.status_code == 200
    assert denied.wsgi_request.user.is_authenticated is False


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_is_single_use_expiring_and_not_logged(client, caplog):
    complete_setup(client)
    caplog.set_level(logging.INFO)
    client.post(reverse("core:password_reset"), {"email": "satish@example.test"})
    message = mail.outbox[0].body
    match = re.search(r"/password-reset/\S+", message)
    assert match is not None
    reset_path = match.group(0)
    assert reset_path not in caplog.text
    assert ADMIN_PASSWORD not in caplog.text

    step = client.post(
        reset_path,
        {
            "new_password1": "replacement-pass-1",
            "new_password2": "replacement-pass-1",
        },
    )
    assert step.status_code == 302
    changed = client.post(
        step.url,
        {
            "new_password1": "replacement-pass-1",
            "new_password2": "replacement-pass-1",
        },
    )
    assert changed.status_code == 302
    reused = client.get(reset_path)
    assert b"invalid or has expired" in reused.content
    assert reset_path not in " ".join(
        getattr(record, "http_path", "") for record in caplog.records
    )

    client.post(reverse("core:password_reset"), {"email": "satish@example.test"})
    expired_path = re.search(r"/password-reset/\S+", mail.outbox[1].body).group(0)
    with patch.object(
        PasswordResetTokenGenerator,
        "_now",
        return_value=datetime.now() + timedelta(seconds=3601),
    ):
        expired = client.get(expired_path)
    assert b"invalid or has expired" in expired.content


def test_standard_user_cannot_administer_company_or_users(client):
    complete_setup(client)
    _, standard = ensure_roles()
    User.objects.create_user(
        username="riley",
        email="riley@example.test",
        password="another-strong-pass",
        display_name="Riley",
        role=standard,
    )
    client.post(
        reverse("core:login"),
        {"username": "riley", "password": "another-strong-pass"},
    )
    assert client.get(reverse("core:company_settings")).status_code == 403
    assert client.get(reverse("core:user_list")).status_code == 403
    assert client.get(reverse("core:user_create")).status_code == 403
    admin = User.objects.get(username="satish")
    assert (
        client.post(reverse("core:company_settings"), setup_payload()).status_code
        == 403
    )
    assert client.post(reverse("core:user_create"), {}).status_code == 403
    assert (
        client.post(
            reverse("core:user_set_active", args=[admin.pk]),
            {"active": "0"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("core:user_send_password_reset", args=[admin.pk])
        ).status_code
        == 403
    )


def test_company_values_persist_and_render_in_company_timezone(client):
    complete_setup(client)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    company = CompanySettings.objects.get()
    response = client.post(
        reverse("core:company_settings"),
        {
            "legal_name": company.legal_name,
            "display_name": "Infoshare",
            "industry": company.industry,
            "base_currency": "USD",
            "fiscal_year_start_month": 1,
            "default_timezone": "America/Los_Angeles",
            "lead_stale_days": 14,
            "deal_stale_days": 21,
            "street": "26040 Acero",
            "city": "Mission Viejo",
            "region": "CA",
            "postal_code": "92691",
            "country": "US",
            "offered_services_text": "IT Consulting",
        },
    )
    assert response.status_code == 302
    assert CompanySettings.objects.get().display_name == "Infoshare"

    fixed_now = datetime(2026, 1, 15, 7, 30, tzinfo=UTC)
    with patch("core.identity_views.timezone.now", return_value=fixed_now):
        home = client.get(reverse("core:home"))
    assert b"01-14-2026, 11:30 PM" in home.content
    assert b"America/Los_Angeles" in home.content


def test_login_and_reset_are_throttled(client):
    complete_setup(client)
    for _ in range(5):
        client.post(
            reverse("core:login"),
            {"username": "satish", "password": "wrong-password-1"},
        )
    blocked = client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    assert blocked.status_code == 429

    for _ in range(5):
        client.post(reverse("core:password_reset"), {"email": "satish@example.test"})
    reset = client.post(
        reverse("core:password_reset"),
        {"email": "satish@example.test"},
    )
    assert reset.status_code == 429


@override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
def test_login_sets_secure_cookies_and_post_requires_csrf():
    client = Client()
    complete_setup(client)
    login_page = client.get(reverse("core:login"))
    assert login_page.cookies["csrftoken"]["secure"]
    logged_in = client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    assert logged_in.cookies["sessionid"]["secure"]

    protected = Client(enforce_csrf_checks=True)
    rejected = protected.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    assert rejected.status_code == 403


def test_failed_login_log_omits_password(client, caplog):
    complete_setup(client)
    caplog.set_level(logging.INFO)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": "wrong-password-1"},
    )
    assert "wrong-password-1" not in caplog.text


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_admin_can_invite_disable_and_reset_user(client):
    complete_setup(client)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    _, standard = ensure_roles()
    invited = client.post(
        reverse("core:user_create"),
        {
            "username": "riley",
            "email": "riley@example.test",
            "display_name": "Riley",
            "timezone": "America/Los_Angeles",
            "role": standard.pk,
            "send_invitation": "on",
        },
    )
    assert invited.status_code == 302
    user = User.objects.get(username="riley")
    assert user.is_active
    assert user.is_staff is False
    assert len(mail.outbox) == 1
    assert "/password-reset/" in mail.outbox[0].body
    assert AuditEvent.objects.filter(
        action="user.invited", object_id=str(user.pk)
    ).exists()

    reset = client.post(reverse("core:user_send_password_reset", args=[user.pk]))
    assert reset.status_code == 302
    assert len(mail.outbox) == 2
    assert AuditEvent.objects.filter(
        action="user.password_reset_requested",
        object_id=str(user.pk),
    ).exists()

    created = client.post(
        reverse("core:user_create"),
        {
            "username": "morgan",
            "email": "morgan@example.test",
            "display_name": "Morgan",
            "timezone": "America/Los_Angeles",
            "role": standard.pk,
            "password": "temporary-strong-pass",
            "password_confirmation": "temporary-strong-pass",
        },
    )
    assert created.status_code == 302
    assert User.objects.get(username="morgan").check_password("temporary-strong-pass")
    assert len(mail.outbox) == 2

    disabled = client.post(
        reverse("core:user_set_active", args=[user.pk]),
        {"active": "0"},
    )
    assert disabled.status_code == 302
    user.refresh_from_db()
    assert user.is_active is False
    assert AuditEvent.objects.filter(
        action="user.disabled", object_id=str(user.pk)
    ).exists()
    blocked_reset = client.post(
        reverse("core:user_send_password_reset", args=[user.pk])
    )
    assert blocked_reset.status_code == 422
    admin = User.objects.get(username="satish")
    cannot_disable_self = client.post(
        reverse("core:user_set_active", args=[admin.pk]),
        {"active": "0"},
    )
    assert cannot_disable_self.status_code == 422
    admin.refresh_from_db()
    assert admin.is_active is True


def test_logo_requires_matching_extension_mime_and_signature():
    valid = SimpleUploadedFile(
        "logo.png",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00",
        content_type="image/png",
    )
    form = SetupForm(setup_payload(), {"logo": valid})
    assert form.is_valid(), form.errors

    disguised = SimpleUploadedFile(
        "logo.png",
        b"<script>alert(1)</script>",
        content_type="image/png",
    )
    form = SetupForm(setup_payload(), {"logo": disguised})
    assert form.is_valid() is False
    assert "not a valid" in form.errors["logo"][0]

    wrong_extension = SimpleUploadedFile(
        "logo.txt",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00",
        content_type="image/png",
    )
    form = SetupForm(setup_payload(), {"logo": wrong_extension})
    assert form.is_valid() is False
    assert "must use" in form.errors["logo"][0]


def test_concurrent_setup_integrity_error_becomes_safe_rerun():
    profile = SetupForm(setup_payload())
    assert profile.is_valid()
    with (
        patch("core.services.User.objects.exists", side_effect=[False, False]),
        patch(
            "core.services.CompanySettings.objects.exists",
            side_effect=[False, True],
        ),
        patch(
            "core.services.CompanySettings.objects.create",
            side_effect=IntegrityError("duplicate singleton"),
        ),
        pytest.raises(SetupAlreadyCompleted),
    ):
        setup_first_administrator(
            profile=profile.company_profile(),
            admin_user={
                "username": "satish",
                "email": "satish@example.test",
                "display_name": "Satish",
            },
            password=ADMIN_PASSWORD,
        )


def test_django_admin_is_not_exposed(client):
    complete_setup(client)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    assert client.get("/admin/").status_code == 404
