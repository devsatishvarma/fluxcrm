"""Age, stage duration, lead rating, and task creation."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.display import duration_phrase, elapsed_phrase
from core.models import StageHistory
from core.taxonomy import ensure_picklists
from leads.models import Lead
from sales.models import Deal
from tests.test_activities import make_deal, make_lead
from tests.test_pipeline import lead_form, make_user

pytestmark = pytest.mark.django_db


def test_ages_are_whole_days():
    assert duration_phrase(0) == "0 days"
    assert duration_phrase(180) == "0 days"
    assert duration_phrase(86400) == "1 day"
    start = timezone.now() - timedelta(days=3, hours=5)
    assert elapsed_phrase(start) == "3 days"


def test_lead_rating_age_and_stage_time_are_visible(client):
    ensure_picklists()
    admin = make_user("jordan", admin=True)
    client.force_login(admin)
    created = client.post(
        reverse("leads:create"),
        lead_form(email="hot@example.test", rating="HOT"),
    )
    assert created.status_code == 302
    lead = Lead.objects.get(email="hot@example.test")
    entered = timezone.now() - timedelta(hours=5)
    created_at = timezone.now() - timedelta(days=3)
    Lead.objects.filter(pk=lead.pk).update(
        created_at=created_at,
        stage_entered_at=entered,
    )
    StageHistory.objects.create(
        object_type="lead",
        object_id=lead.pk,
        from_stage="",
        to_stage="NEW",
        duration_seconds=0,
        reason="Phase 3 baseline",
    )
    page = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"Lead rating" in page.content
    assert b"Hot" in page.content
    assert b"Lead Age" in page.content
    assert b"Stage-Age" in page.content
    assert b"3 days" in page.content
    assert b"0 days" in page.content
    assert b"hour" not in page.content
    assert b"minute" not in page.content
    assert b"Started in New" in page.content
    assert b"Phase 3 baseline" not in page.content
    assert b"0 seconds" not in page.content
    assert b"by after" not in page.content
    listed = client.get(reverse("leads:list"), {"rating": "HOT"})
    assert b"Ada" in listed.content
    assert b"Hot" in listed.content
    cold = client.get(reverse("leads:list"), {"rating": "COLD"})
    assert lead.first_name.encode() not in cold.content
    rejected = client.post(
        "/api/v1/leads/",
        lead_form(email="bad-temp@example.test", rating="LUKEWARM"),
        content_type="application/json",
    )
    assert rejected.status_code == 422


def test_deal_history_explains_a_baseline_and_a_real_move(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    deal = make_deal(admin, lead)
    Deal.objects.filter(pk=deal.pk).update(
        stage="PROPOSAL",
        stage_entered_at=timezone.now() - timedelta(days=2),
        created_at=timezone.now() - timedelta(days=9),
    )
    StageHistory.objects.create(
        object_type="deal",
        object_id=deal.pk,
        from_stage="",
        to_stage="PROPOSAL",
        duration_seconds=0,
        probability_snapshot="50.00",
        reason="Phase 3 baseline",
    )
    StageHistory.objects.create(
        object_type="deal",
        object_id=deal.pk,
        from_stage="DISCOVERY",
        to_stage="PROPOSAL",
        duration_seconds=180,
        probability_snapshot="50.00",
        reason="Proposal sent",
        changed_by=admin,
    )
    client.force_login(admin)
    page = client.get(reverse("sales:detail", args=[deal.pk]))
    text = page.content.decode()
    assert "Started in Proposal" in text
    assert "Phase 3 baseline" not in text
    assert "0 seconds" not in text
    assert "Moved from Discovery to Proposal" in text
    assert text.index("Stage history") > text.index("Timeline")
    assert text.index("Delete deal") > text.index("Stage history")
    assert '<details class="stage-history">' in text
    assert '<details class="stage-history" open' not in text
    assert "Spent 0 days in Discovery" in text
    assert f"Recorded by {admin.display_name}" in text
    assert "9 days" in text
    assert "2 days" in text
    assert "Deal confidence</dt><dd>Low</dd>" in text
    assert "Medium" in text
    assert "Temperature" not in text
    assert "Warm" not in text


def test_task_can_be_added_from_a_record_and_the_task_list(client):
    admin = make_user("jordan", admin=True)
    lead = make_lead(admin)
    client.force_login(admin)
    detail = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"Add task" in detail.content
    due = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    saved = client.post(
        reverse("activities:task_create"),
        {
            "kind": "lead",
            "object_id": str(lead.pk),
            "title": "Send the agenda",
            "due_at": due,
            "priority": "HIGH",
        },
    )
    assert saved.status_code == 302
    follow = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"Send the agenda" in follow.content
    listed = client.get(reverse("activities:tasks"))
    assert b'id="task-title"' in listed.content
    again = client.post(
        reverse("activities:task_create"),
        {
            "lead_id": str(lead.pk),
            "title": "Confirm the attendees",
            "due_at": due,
            "priority": "NORMAL",
        },
    )
    assert again.status_code == 302
    assert b"Confirm the attendees" in client.get(again.headers["Location"]).content
