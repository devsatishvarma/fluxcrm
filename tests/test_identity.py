import logging
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse

from audit.models import AuditEvent
from core.services import ensure_roles
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
    assert b"2026-01-14 23:30" in home.content
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
