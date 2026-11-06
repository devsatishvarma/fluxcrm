"""Phase 4 follow-up, reminder, and timeline gates."""

import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from activities.models import Activity, ActivityLink, Reminder, Task
from activities.services import create_activity, create_task
from audit.models import AuditEvent
from core.models import JobRun
from core.taxonomy import ensure_picklists
from identity.models import Role, User
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
            "confidence": "MEDIUM",
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
            "with_party": f"lead:{lead.pk}",
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
    assert lead_page.content.count(b"<strong>Shared discovery call</strong>") == 1
    assert deal_page.content.count(b"<strong>Shared discovery call</strong>") == 1
    assert lead_page.content.count(b"<div>private call notes</div>") == 1
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
    assert task.description == "private task notes"
    completed_event = AuditEvent.objects.get(action="task.completed")
    assert completed_event.before_json["status"] == "OPEN"
    assert completed_event.after_json["status"] == "DONE"
    assert "private task notes" not in json.dumps(completed_event.after_json)
    noted = create_task(
        actor=admin,
        data={
            "title": "Send the follow-up",
            "description": "Started the call",
            "due_at": timezone.now() - timedelta(hours=1),
        },
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    listed = client.get(reverse("activities:tasks"))
    assert b'name="completion_notes"' in listed.content
    assert b'placeholder="Add notes"' in listed.content
    finished = client.post(
        reverse("activities:complete", args=[noted.pk]),
        {"version": noted.version, "completion_notes": "They asked for a quote"},
    )
    assert finished.status_code == 302
    noted.refresh_from_db()
    assert noted.description == "Started the call\nThey asked for a quote"

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
        (
            "Summer check",
            datetime(2026, 7, 15, 17, 0, tzinfo=UTC),
            "07-15-2026, 10:00 AM",
        ),
        (
            "Fallback check",
            datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
            "11-01-2026, 01:30 AM",
        ),
        (
            "Spring check",
            datetime(2026, 3, 8, 10, 30, tzinfo=UTC),
            "03-08-2026, 03:30 AM",
        ),
    )
    for subject, occurred_at, _rendered in samples:
        create_activity(
            actor=admin,
            data={
                "activity_type": "CALL",
                "subject": subject,
                "with_party": f"lead:{lead.pk}",
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
    assert 'name="with_party"' in html
    assert f'name="with_party" value="lead:{lead.pk}" checked' in html
    assert "party-search" in html
    assert 'class="party-menu" id="quick-activity-with-menu" hidden' in html
    assert 'class="party-list"' in html
    assert "Jamie Ng" in html
    assert "Create the contact or lead first" in html
    assert 'name="occurred_at"' in html
    assert 'name="body"' in html
    assert 'value="NOTE"' in html
    assert 'tag === "INPUT"' in html
    assert "isContentEditable" in html
    saved = client.post(
        reverse("activities:activity_create"),
        {
            "kind": "lead",
            "object_id": str(lead.pk),
            "activity_type": "CALL",
            "subject": "Quick intro",
            "with_party": f"lead:{lead.pk}",
            "occurred_at": "2026-07-15T10:00",
            "body": "Left a message",
        },
    )
    assert saved.status_code == 302
    recorded = Activity.objects.get(subject="Quick intro")
    assert recorded.links.get().object_id == lead.pk
    assert recorded.with_lead_id == lead.pk
    assert recorded.with_whom == "Jamie Ng"
    assert recorded.body == "Left a message"
    assert recorded.occurred_at is not None
    saved_note = client.post(
        reverse("activities:activity_create"),
        {
            "kind": "lead",
            "object_id": str(lead.pk),
            "activity_type": "NOTE",
            "subject": "A leftover note",
            "with_party": f"lead:{lead.pk}",
            "occurred_at": "2026-07-15T10:00",
            "body": "Remember the follow-up",
        },
    )
    assert saved_note.status_code == 302
    noted = Activity.objects.get(subject="A leftover note")
    assert noted.activity_type == "NOTE"
    assert noted.body == "Remember the follow-up"
    invalid = client.post(
        reverse("activities:activity_create"),
        {"kind": "lead", "object_id": str(lead.pk), "activity_type": "CALL"},
    )
    assert invalid.status_code == 422
    assert Activity.objects.filter(subject="").count() == 0
    unknown = client.post(
        reverse("activities:activity_create"),
        {
            "kind": "lead",
            "object_id": str(lead.pk),
            "activity_type": "CALL",
            "subject": "Call with a new name",
            "with_whom": "Pat New",
            "occurred_at": "2026-07-15T10:00",
        },
    )
    assert unknown.status_code == 422
    assert b"Create that person first" in unknown.content
    assert Activity.objects.filter(subject="Call with a new name").count() == 0


def test_task_buckets_and_stale_badges_stay_flat(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin, company="Current Co")
    stale_lead = make_lead(admin, company="Quiet Co")
    Lead.objects.filter(pk=stale_lead.pk).update(
        created_at=timezone.now() - timedelta(days=30)
    )
    now = timezone.now()
    zone = ZoneInfo("America/Los_Angeles")
    local_now = now.astimezone(zone)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    later_today = create_task(
        actor=admin,
        data={
            "title": "Later today",
            "due_at": start + timedelta(days=1) - timedelta(minutes=1),
        },
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
    opened = client.get(reverse("activities:tasks"))
    due = client.get(reverse("activities:tasks") + "?bucket=due")
    overdue = client.get(reverse("activities:tasks") + "?bucket=overdue")
    upcoming = client.get(reverse("activities:tasks") + "?bucket=upcoming")
    assert b"Later today" in opened.content
    assert b"Already late" in opened.content
    assert b"Next week" in opened.content
    assert b"Later today" in due.content
    assert b"Already late" not in due.content
    assert b"Next week" not in due.content
    assert b"Already late" in overdue.content
    assert b"Later today" not in overdue.content
    assert b"Next week" in upcoming.content
    client.post(
        reverse("activities:complete", args=[later_today.pk]),
        {"version": later_today.version},
    )
    done = client.get(reverse("activities:tasks") + "?bucket=done")
    assert b"Later today" in done.content
    assert b"Completed" in done.content
    opened_again = client.get(reverse("activities:tasks"))
    assert b"Later today" not in opened_again.content
    listed = client.get(reverse("leads:list"))
    assert b"Quiet Co" in listed.content
    assert b"Stale" in listed.content
    assert b"Current" in listed.content
    anonymous = client.__class__()
    assert anonymous.get(reverse("activities:tasks")).status_code == 302
    assert User.objects.filter(username="jordan").exists()
    assert Deal.objects.filter(lead=lead).count() == 0


def test_task_links_and_hold_cancel_delete(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    deal = make_deal(admin, lead)
    now = timezone.now()
    task = create_task(
        actor=admin,
        data={"title": "Call Jamie", "due_at": now - timedelta(days=1)},
        links=[
            {"kind": "lead", "id": lead.pk},
            {"kind": "deal", "id": deal.pk},
        ],
        request_id="test",
    )
    client.force_login(admin)
    overdue = client.get(reverse("activities:tasks") + "?bucket=overdue")
    assert b"Jamie Ng" in overdue.content
    assert b"Security assessment" in overdue.content
    assert b"Cancel" in overdue.content
    assert b"Hold" in overdue.content
    assert b"Delete" in overdue.content
    held = client.post(
        reverse("activities:hold", args=[task.pk]),
        {"version": task.version},
    )
    assert held.status_code == 302
    task.refresh_from_db()
    assert task.status == Task.Status.HOLD
    held_page = client.get(reverse("activities:tasks") + "?bucket=held")
    assert b"Call Jamie" in held_page.content
    assert b"Resume" in held_page.content
    still_overdue = client.get(reverse("activities:tasks") + "?bucket=overdue")
    assert b"Call Jamie" not in still_overdue.content
    cancelled = client.post(
        reverse("activities:cancel", args=[task.pk]),
        {"version": task.version},
    )
    assert cancelled.status_code == 302
    task.refresh_from_db()
    assert task.status == Task.Status.CANCELLED
    removed = client.post(
        reverse("activities:delete", args=[task.pk]),
        {
            "version": task.version,
            "delete_reason": "Added on the wrong lead",
            "confirm_delete": "yes",
        },
    )
    assert removed.status_code == 302
    assert Task.objects.filter(pk=task.pk).count() == 0
    reader = User.objects.create_user(
        username="executive",
        email="executive@example.test",
        password="another-strong-pass",
        display_name="Executive",
        role=Role.objects.get(key="READ_ONLY"),
    )
    other = create_task(
        actor=admin,
        data={"title": "Keep this", "due_at": now - timedelta(hours=2)},
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    client.force_login(reader)
    denied = client.post(
        reverse("activities:delete", args=[other.pk]),
        {"version": other.version, "delete_reason": "Should not delete"},
    )
    assert denied.status_code == 403
    assert Task.objects.filter(pk=other.pk).exists()


def test_activity_can_be_edited_and_deleted(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    activity = create_activity(
        actor=admin,
        data={
            "activity_type": "EMAIL",
            "subject": "Wrong company note",
            "with_party": f"lead:{lead.pk}",
            "body": "private notebook",
            "occurred_at": datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
        },
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    client.force_login(admin)
    page = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"detail-fields" in page.content
    assert b">Edit</summary>" in page.content
    assert b">Delete</summary>" in page.content
    assert b">Jamie Ng</a>" in page.content
    updated = client.post(
        reverse("activities:activity_update", args=[activity.pk]),
        {
            "version": activity.version,
            "kind": "lead",
            "object_id": str(lead.pk),
            "activity_type": "CALL",
            "subject": "Corrected call",
            "with_party": f"lead:{lead.pk}",
            "body": "private notebook",
            "occurred_at": "2026-08-01T09:00",
            "outcome": "Reached Jamie",
        },
    )
    assert updated.status_code == 302
    activity.refresh_from_db()
    assert activity.subject == "Corrected call"
    event = AuditEvent.objects.filter(action="activity.updated").get()
    assert "private notebook" not in json.dumps(event.after_json)
    deleted = client.post(
        reverse("activities:activity_delete", args=[activity.pk]),
        {
            "version": activity.version,
            "kind": "lead",
            "object_id": str(lead.pk),
            "delete_reason": "Added on the wrong record",
            "confirm_delete": "yes",
        },
    )
    assert deleted.status_code == 302
    assert Activity.objects.filter(pk=activity.pk).count() == 0


def test_activity_with_whom_must_be_an_existing_contact_or_lead(client):
    from accounts.services import create_account, create_contact

    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    account = create_account(
        actor=admin,
        data={"name": "Northwind", "account_type": "CUSTOMER"},
    )
    contact = create_contact(
        actor=admin,
        data={
            "first_name": "Avery",
            "last_name": "Cole",
            "email": "avery.cole@example.test",
            "account": account.pk,
        },
    )
    activity = create_activity(
        actor=admin,
        data={
            "activity_type": "MEETING",
            "subject": "Working session",
            "with_party": f"contact:{contact.pk}",
            "occurred_at": datetime(2026, 9, 2, 17, 0, tzinfo=UTC),
        },
        links=[{"kind": "lead", "id": lead.pk}, {"kind": "account", "id": account.pk}],
        request_id="test",
    )
    assert activity.with_contact_id == contact.pk
    assert activity.with_lead_id is None
    assert activity.with_whom == "Avery Cole"
    client.force_login(admin)
    page = client.get(reverse("accounts:detail", args=[account.pk]))
    assert b">Avery Cole</a>" in page.content
    moved = client.post(
        reverse("activities:activity_update", args=[activity.pk]),
        {
            "version": activity.version,
            "kind": "account",
            "object_id": str(account.pk),
            "activity_type": "MEETING",
            "subject": "Working session",
            "with_party": f"lead:{lead.pk}",
            "occurred_at": "2026-09-02T10:00",
        },
    )
    assert moved.status_code == 302
    activity.refresh_from_db()
    assert activity.with_lead_id == lead.pk
    assert activity.with_contact_id is None
    assert activity.with_whom == "Jamie Ng"


def test_task_details_and_notes_can_be_edited(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    task = create_task(
        actor=admin,
        data={
            "title": "Send the recap",
            "description": "First draft",
            "due_at": timezone.now() + timedelta(days=1),
        },
        links=[{"kind": "lead", "id": lead.pk}],
        request_id="test",
    )
    client.force_login(admin)
    page = client.get(reverse("activities:tasks"))
    html = page.content.decode()
    assert html.index("Complete</button>") < html.index(">Edit</summary>")
    assert html.index('class="delete-line"') < html.index(">Delete</button>")
    assert html.index('name="confirm_delete"') < html.index(">Delete</button>")
    updated = client.post(
        reverse("activities:task_update", args=[task.pk]),
        {
            "version": task.version,
            "title": "Send the revised recap",
            "description": "private task notes",
            "due_at": "2026-11-15T10:00",
            "priority": "HIGH",
        },
    )
    assert updated.status_code == 302
    task.refresh_from_db()
    assert task.title == "Send the revised recap"
    assert task.description == "private task notes"
    assert task.priority == "HIGH"
    event = AuditEvent.objects.get(action="task.updated")
    assert "private task notes" not in json.dumps(event.after_json)
    listed = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"private task notes" in listed.content
    assert b'id="quick-task-notes"' in listed.content
    assert b">Hold</button>" not in listed.content
    assert b">Cancel</button>" not in listed.content
    deal = make_deal(admin, lead)
    create_task(
        actor=admin,
        data={
            "title": "Deal follow-up",
            "description": "Deal page notes",
            "due_at": timezone.now() + timedelta(days=2),
        },
        links=[{"kind": "deal", "id": deal.pk}],
        request_id="test",
    )
    deal_page = client.get(reverse("sales:detail", args=[deal.pk]))
    assert b"Deal follow-up" in deal_page.content
    assert b"Deal page notes" not in deal_page.content
    assert b'id="quick-task-notes"' not in deal_page.content
    assert b">Hold</button>" not in deal_page.content
    assert b">Delete</button>" not in deal_page.content
    tasks_page = client.get(reverse("activities:tasks"))
    assert b"<strong>Deal follow-up</strong>" in tasks_page.content
    assert b">Hold</button>" in tasks_page.content


def test_lists_sort_by_rating_and_amount(client):
    admin = make_user("jordan", admin=True)
    cold = make_lead(admin, "Cold Co")
    hot = make_lead(admin, "Hot Co")
    Lead.objects.filter(pk=cold.pk).update(rating="COLD")
    Lead.objects.filter(pk=hot.pk).update(rating="HOT")
    small = make_deal(admin, cold)
    large = make_deal(admin, hot)
    Deal.objects.filter(pk=small.pk).update(amount="10.00", title="Small deal")
    Deal.objects.filter(pk=large.pk).update(amount="900.00", title="Large deal")
    client.force_login(admin)
    leads = client.get(reverse("leads:list") + "?ordering=rating")
    assert leads.status_code == 200
    assert leads.content.index(b"Cold Co") < leads.content.index(b"Hot Co")
    deals = client.get(reverse("sales:list") + "?ordering=-amount")
    assert deals.content.index(b"Large deal") < deals.content.index(b"Small deal")
    accounts = client.get(reverse("accounts:list") + "?ordering=name")
    assert b"Sort" in accounts.content
