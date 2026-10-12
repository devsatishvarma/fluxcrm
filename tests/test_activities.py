"""Phase 4 follow-up, reminder, and timeline gates."""

import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from activities.models import Activity, ActivityLink, Reminder, Task
from activities.services import create_activity, create_task
from audit.models import AuditEvent
from core.models import JobRun
from core.taxonomy import ensure_picklists
from identity.models import User
from leads.models import Lead
from leads.services import create_lead
from sales.models import Deal
from sales.services import create_deal
from tests.test_pipeline import make_user

pytestmark = pytest.mark.django_db


def make_lead(actor, company="Pinecone Health Group"):
    ensure_picklists()
    slug = "".join(character for character in company.lower() if character.isalnum())
    return create_lead(
        actor=actor,
        data={
            "first_name": "Jamie",
            "last_name": "Ng",
            "company_name": company,
            "source": "WEB",
            "email": f"{slug}@example.test",
        },
        request_id="test",
    )


def make_deal(actor, lead):
    return create_deal(
        actor=actor,
        data={
            "title": "Security assessment",
            "lead": str(lead.pk),
            "deal_type": "CONSULTING_SERVICES",
            "temperature": "WARM",
            "amount": "100.00",
            "currency": "USD",
        },
        request_id="test",
    )


def test_one_activity_appears_once_on_every_linked_record(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    deal = make_deal(admin, lead)
    activity = create_activity(
        actor=admin,
        data={
            "activity_type": "CALL",
            "subject": "Shared discovery call",
            "body": "private call notes",
            "occurred_at": datetime(2026, 7, 15, 17, 0, tzinfo=UTC),
        },
        links=[
            {"kind": "lead", "id": lead.pk},
            {"kind": "deal", "id": deal.pk},
        ],
        request_id="test",
    )
    assert Activity.objects.count() == 1
    assert ActivityLink.objects.filter(activity=activity).count() == 2
    client.force_login(admin)
    lead_page = client.get(reverse("leads:detail", args=[lead.pk]))
    deal_page = client.get(reverse("sales:detail", args=[deal.pk]))
    assert lead_page.content.count(b"Shared discovery call") == 1
    assert deal_page.content.count(b"Shared discovery call") == 1
    assert b"private call notes" not in lead_page.content
    event = AuditEvent.objects.get(
        action="activity.created", object_id=str(activity.pk)
    )
    assert "private call notes" not in json.dumps(event.after_json)


def test_complete_and_snooze_stay_consistent_with_audit(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    task = create_task(
        actor=admin,
        data={
            "title": "Send the recap",
            "description": "private task notes",
            "due_at": timezone.now() - timedelta(hours=1),
        },
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    client.force_login(admin)
    other = make_user("morgan")
    other_client = client.__class__()
    other_client.force_login(other)
    denied = other_client.post(
        reverse("activities:complete", args=[task.pk]),
        {"version": task.version},
    )
    assert denied.status_code == 403
    conflict = client.post(
        f"/api/v1/tasks/{task.pk}/complete/",
        {"version": task.version + 5},
        content_type="application/json",
    )
    assert conflict.status_code == 409
    completed = client.post(
        reverse("activities:complete", args=[task.pk]),
        {"version": task.version},
    )
    assert completed.status_code == 302
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert task.completed_at is not None
    assert task.version == 2
    completed_event = AuditEvent.objects.get(action="task.completed")
    assert completed_event.before_json["status"] == "OPEN"
    assert completed_event.after_json["status"] == "DONE"
    assert "private task notes" not in json.dumps(completed_event.after_json)

    open_task = create_task(
        actor=admin,
        data={"title": "Book the room", "due_at": timezone.now() - timedelta(hours=2)},
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    snooze_until = timezone.now() + timedelta(days=2)
    snoozed = client.post(
        f"/api/v1/tasks/{open_task.pk}/snooze/",
        {"version": open_task.version, "snooze_until": snooze_until.isoformat()},
        content_type="application/json",
    )
    assert snoozed.status_code == 200
    open_task.refresh_from_db()
    assert open_task.status == Task.Status.OPEN
    assert open_task.snooze_until is not None
    assert open_task.reminder_sent_at is None
    assert open_task.version == 2
    snooze_event = AuditEvent.objects.get(action="task.snoozed")
    assert snooze_event.after_json["status"] == "OPEN"
    assert snooze_event.after_json["snooze_until"]


def test_due_times_render_across_dst_boundaries(client):
    admin = make_user("jordan", admin=True)
    assert admin.timezone == "America/Los_Angeles"
    lead = make_lead(admin)
    samples = (
        ("Summer check", datetime(2026, 7, 15, 17, 0, tzinfo=UTC), "2026-07-15 10:00"),
        (
            "Fallback check",
            datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
            "2026-11-01 01:30",
        ),
        ("Spring check", datetime(2026, 3, 8, 10, 30, tzinfo=UTC), "2026-03-08 03:30"),
    )
    for subject, occurred_at, _rendered in samples:
        create_activity(
            actor=admin,
            data={
                "activity_type": "NOTE",
                "subject": subject,
                "occurred_at": occurred_at,
            },
            links=[{"kind": "lead", "id": lead.pk}],
            request_id="test",
        )
    client.force_login(admin)
    page = client.get(reverse("leads:detail", args=[lead.pk]))
    for subject, _occurred_at, rendered in samples:
        assert subject.encode() in page.content
        assert rendered.encode() in page.content


def test_repeated_scheduler_runs_do_not_duplicate_reminders():
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    create_task(
        actor=admin,
        data={"title": "Call back", "due_at": datetime(2026, 10, 11, 15, tzinfo=UTC)},
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    first_minute = datetime(2026, 10, 11, 16, 0, tzinfo=UTC)
    with patch(
        "core.management.commands.run_due_jobs.timezone.now",
        return_value=first_minute,
    ):
        call_command("run_due_jobs")
        call_command("run_due_jobs")
    assert Reminder.objects.count() == 1
    assert (
        JobRun.objects.filter(name="due_jobs", status=JobRun.Status.SUCCEEDED).count()
        == 1
    )


def test_failed_jobs_retry_on_a_later_minute_without_a_duplicate(caplog):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    create_task(
        actor=admin,
        data={
            "title": "Send pricing",
            "due_at": datetime(2026, 10, 11, 15, tzinfo=UTC),
        },
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    first_minute = datetime(2026, 10, 11, 16, 0, tzinfo=UTC)
    later_minute = first_minute + timedelta(minutes=1)
    caplog.set_level(logging.ERROR)
    with (
        patch(
            "core.management.commands.run_due_jobs.timezone.now",
            return_value=first_minute,
        ),
        patch(
            "activities.jobs.deliver_due_reminders",
            side_effect=RuntimeError("scheduler down"),
        ),
        pytest.raises(RuntimeError, match="scheduler down"),
    ):
        call_command("run_due_jobs")
    assert JobRun.objects.get(name="due_jobs").status == JobRun.Status.FAILED
    assert Reminder.objects.count() == 0
    assert "Scheduled job run failed" in caplog.text
    with patch(
        "core.management.commands.run_due_jobs.timezone.now",
        return_value=first_minute,
    ):
        call_command("run_due_jobs")
    assert JobRun.objects.filter(name="due_jobs").count() == 1
    with patch(
        "core.management.commands.run_due_jobs.timezone.now",
        return_value=later_minute,
    ):
        call_command("run_due_jobs")
    assert Reminder.objects.count() == 1
    assert JobRun.objects.filter(status=JobRun.Status.FAILED).count() == 1
    assert JobRun.objects.filter(status=JobRun.Status.SUCCEEDED).count() == 1


def test_quick_add_defaults_the_record_and_ignores_form_fields(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    client.force_login(admin)
    page = client.get(reverse("leads:detail", args=[lead.pk]))
    html = page.content.decode()
    assert 'id="quick-activity"' in html
    assert f'name="object_id" value="{lead.pk}"' in html
    assert 'value="CALL" selected' in html
    assert 'tag === "INPUT"' in html
    assert "isContentEditable" in html
    saved = client.post(
        reverse("activities:activity_create"),
        {
            "kind": "lead",
            "object_id": str(lead.pk),
            "activity_type": "CALL",
            "subject": "Quick intro",
        },
    )
    assert saved.status_code == 302
    assert Activity.objects.get(subject="Quick intro").links.get().object_id == lead.pk
    invalid = client.post(
        reverse("activities:activity_create"),
        {"kind": "lead", "object_id": str(lead.pk), "activity_type": "CALL"},
    )
    assert invalid.status_code == 422
    assert Activity.objects.filter(subject="").count() == 0


def test_task_buckets_and_stale_badges_stay_flat(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin, company="Current Co")
    stale_lead = make_lead(admin, company="Quiet Co")
    Lead.objects.filter(pk=stale_lead.pk).update(
        created_at=timezone.now() - timedelta(days=30)
    )
    now = timezone.now()
    create_task(
        actor=admin,
        data={"title": "Due now", "due_at": now},
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    create_task(
        actor=admin,
        data={"title": "Already late", "due_at": now - timedelta(days=2)},
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    create_task(
        actor=admin,
        data={"title": "Next week", "due_at": now + timedelta(days=7)},
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    client.force_login(admin)
    due = client.get(reverse("activities:tasks"))
    overdue = client.get(reverse("activities:tasks") + "?bucket=overdue")
    upcoming = client.get(reverse("activities:tasks") + "?bucket=upcoming")
    assert b"Due now" in due.content
    assert b"Already late" not in due.content
    assert b"Already late" in overdue.content
    assert b"Next week" in upcoming.content
    listed = client.get(reverse("leads:list"))
    assert b"Quiet Co" in listed.content
    assert b"Stale" in listed.content
    assert b"Current" in listed.content
    anonymous = client.__class__()
    assert anonymous.get(reverse("activities:tasks")).status_code == 302
    assert User.objects.filter(username="jordan").exists()
    assert Deal.objects.filter(lead=lead).count() == 0
