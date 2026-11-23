"""Phase 10C Microsoft Graph shared-mailbox outbound mail."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from activities.jobs import deliver_due_reminders
from activities.models import Reminder
from activities.services import create_task
from audit.models import AuditEvent
from identity.models import Role, User
from tests.test_activities import make_lead
from tests.test_identity import ADMIN_PASSWORD, complete_setup
from tests.test_pipeline import make_user

pytestmark = pytest.mark.django_db

GRAPH_SETTINGS = {
    "AZURE_TENANT_ID": "tenant-id",
    "AZURE_CLIENT_ID": "client-id",
    "AZURE_CLIENT_SECRET": "client-secret",
    "GRAPH_SHARED_MAILBOX": "crm@example.test",
    "PUBLIC_BASE_URL": "https://crm.example.test",
    "PASSWORD_RESET_ENABLED": True,
    "MFA_REQUIRED": False,
}


@pytest.fixture
def graph_settings(settings):
    for key, value in GRAPH_SETTINGS.items():
        setattr(settings, key, value)
    settings.EMAIL_BACKEND = "core.mail_backend.GraphSharedMailboxBackend"
    settings.DEFAULT_FROM_EMAIL = "crm@example.test"


def _make_task(owner, title="Follow up"):
    lead = make_lead(owner)
    return create_task(
        actor=owner,
        data={
            "title": title,
            "description": "private notes stay out of audit email count",
            "due_at": timezone.now() - timedelta(minutes=5),
        },
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )


def test_email_task_sends_to_owner_and_watchers(client, graph_settings):
    complete_setup(client)
    satish = User.objects.get(username="satish")
    watcher = User.objects.create_user(
        username="riley",
        email="riley@example.test",
        password="another-strong-pass",
        display_name="Riley",
        role=Role.objects.get(key="STANDARD_USER"),
    )
    task = _make_task(satish)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    with patch("activities.mail.send_crm_mail") as send_mail:
        response = client.post(
            reverse("activities:email", args=[task.pk]),
            {"watcher_ids": [str(watcher.pk)]},
        )
    assert response.status_code == 302
    send_mail.assert_called_once()
    kwargs = send_mail.call_args.kwargs
    assert set(kwargs["to_addresses"]) == {
        "satish@example.test",
        "riley@example.test",
    }
    assert "https://crm.example.test/tasks/" in kwargs["body_text"]
    assert AuditEvent.objects.filter(action="task.emailed").exists()


def test_email_task_requires_graph_configuration(client, settings):
    settings.MFA_REQUIRED = False
    settings.AZURE_TENANT_ID = ""
    settings.AZURE_CLIENT_ID = ""
    settings.AZURE_CLIENT_SECRET = ""
    settings.GRAPH_SHARED_MAILBOX = ""
    complete_setup(client)
    satish = User.objects.get(username="satish")
    task = _make_task(satish)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    response = client.post(reverse("activities:email", args=[task.pk]))
    assert response.status_code == 302
    assert not AuditEvent.objects.filter(action="task.emailed").exists()


def test_reminder_email_once_and_retries_do_not_duplicate(graph_settings):
    owner = make_user("jordan", admin=True)
    task = _make_task(owner)
    with patch("activities.mail.send_crm_mail") as send_mail:
        first = deliver_due_reminders(timezone.now())
        second = deliver_due_reminders(timezone.now())
    assert first["reminders"] == 1
    assert first["reminder_emails"] == 1
    assert second["reminders"] == 0
    assert second["reminder_emails"] == 0
    assert send_mail.call_count == 1
    reminder = Reminder.objects.get(task=task)
    assert reminder.email_sent_at is not None


def test_reminder_email_failure_keeps_in_app_row_and_retries(graph_settings):
    owner = make_user("jordan", admin=True)
    task = _make_task(owner, title="Retry mail")
    with patch(
        "activities.mail.send_crm_mail",
        side_effect=ValidationError("The email could not be delivered."),
    ):
        first = deliver_due_reminders(timezone.now())
    assert first["reminders"] == 1
    assert first["reminder_email_failures"] >= 1
    reminder = Reminder.objects.get(task=task)
    assert reminder.email_sent_at is None
    with patch("activities.mail.send_crm_mail") as send_mail:
        second = deliver_due_reminders(timezone.now())
    assert second["reminders"] == 0
    assert second["reminder_emails"] == 1
    send_mail.assert_called_once()
    reminder.refresh_from_db()
    assert reminder.email_sent_at is not None


def test_graph_backend_sends_password_reset_through_shared_mailbox(
    client, graph_settings
):
    complete_setup(client)
    with patch("core.mail_backend.send_graph_mail") as send_mail:
        response = client.post(
            reverse("core:password_reset"),
            {"email": "satish@example.test"},
        )
    assert response.status_code == 302
    send_mail.assert_called_once()
    assert send_mail.call_args.kwargs["to_addresses"] == ["satish@example.test"]


def test_help_mentions_graph_task_and_reminder_mail(client, settings):
    settings.MFA_REQUIRED = False
    complete_setup(client)
    client.post(
        reverse("core:login"),
        {"username": "satish", "password": ADMIN_PASSWORD},
    )
    help_page = client.get(reverse("core:help"))
    assert b"Email task" in help_page.content
    assert b"shared mailbox" in help_page.content
