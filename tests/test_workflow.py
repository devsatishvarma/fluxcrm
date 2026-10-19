from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from core.models import PicklistValue, StageHistory
from core.taxonomy import ensure_picklists
from core.workflow import DEAL_GRAPH, LEAD_GRAPH, allowed_targets
from leads.models import Lead
from leads.services import transition_lead
from sales.models import Deal
from sales.services import open_pipeline_total, transition_deal, update_deal
from tests.test_pipeline import lead_form, make_user

pytestmark = pytest.mark.django_db


def deal_form(lead_id, **overrides):
    payload = {
        "title": "Assessment",
        "lead": str(lead_id),
        "deal_type": "CONSULTING_SERVICES",
        "amount": "100.00",
        "currency": "USD",
        "confidence": "MEDIUM",
        "stage": "NEW",
    }
    payload.update(overrides)
    return payload


def test_lead_moves_share_one_service_across_ui_and_api(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    owner = make_user("riley")
    api = APIClient()
    api.force_authenticate(user=admin)
    created = api.post(
        "/api/v1/leads/",
        lead_form(owner=owner.pk, email="workflow@example.test"),
        format="json",
    )
    lead = Lead.objects.get(pk=created.json()["id"])
    with pytest.raises(ValidationError, match="not allowed"):
        transition_lead(
            actor=admin,
            lead_id=lead.pk,
            version=lead.version,
            to_stage="SQL",
            reason="skip",
        )
    lead.refresh_from_db()
    assert lead.stage == "NEW"

    client.force_login(admin)
    blocked = client.post(
        reverse("leads:transition", args=[lead.pk]),
        {"version": lead.version, "to_stage": "SQL", "reason": "skip"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert blocked.status_code == 422
    assert b"not allowed" in blocked.content
    missing = client.post(
        reverse("leads:transition", args=[lead.pk]),
        {"version": lead.version, "to_stage": "CONTACTED", "reason": "called"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert missing.status_code == 422
    assert b"contact_substatus" in missing.content
    lead.refresh_from_db()
    assert lead.stage == "NEW"

    lead.stage_entered_at = timezone.now() - timedelta(seconds=180)
    lead.save(update_fields=["stage_entered_at"])
    moved = client.post(
        reverse("leads:transition", args=[lead.pk]),
        {
            "version": lead.version,
            "to_stage": "CONTACTED",
            "reason": "called the office",
            "contact_substatus": "ATTEMPTED",
        },
    )
    assert moved.status_code == 302
    lead.refresh_from_db()
    assert lead.stage == "CONTACTED"
    stale = client.post(
        reverse("leads:transition", args=[lead.pk]),
        {
            "version": 1,
            "to_stage": "ARCHIVED",
            "reason": "stale write",
        },
    )
    assert stale.status_code == 409
    lead.refresh_from_db()
    assert lead.stage == "CONTACTED"

    history = api.get(f"/api/v1/leads/{lead.pk}/history/")
    row = history.json()[0]
    assert history.status_code == 200
    assert row["changed_by"] == admin.pk
    assert row["from_stage"] == "NEW"
    assert row["to_stage"] == "CONTACTED"
    assert row["reason"] == "called the office"
    assert row["duration_seconds"] >= 180
    assert row["probability_snapshot"] is None
    assert AuditEvent.objects.filter(
        action="lead.stage_changed", object_id=str(lead.pk)
    ).exists()

    api_lead = api.post(
        "/api/v1/leads/",
        lead_form(email="api@example.test"),
        format="json",
    )
    api_id = api_lead.json()["id"]
    rejected = api.post(
        f"/api/v1/leads/{api_id}/transition/",
        {"version": 1, "to_stage": "MQL", "reason": "too soon"},
        format="json",
    )
    assert rejected.status_code == 422
    accepted = api.post(
        f"/api/v1/leads/{api_id}/transition/",
        {
            "version": 1,
            "to_stage": "CONTACTED",
            "reason": "reached them",
            "contact_substatus": "IN_CONTACT",
        },
        format="json",
    )
    assert accepted.status_code == 200
    assert accepted.json()["stage"] == "CONTACTED"

    board = client.get(reverse("leads:board"))
    assert b"Lovelace" in board.content
    assert b"Move" in board.content
    assert b"board-error" in board.content
    assert b'name="contact_substatus"' not in board.content
    assert b"X-Requested-With" in board.content
    detail = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"called the office" in detail.content
    path = detail.content.split(b'class="stage-path"', 1)[1].split(b"</ol>", 1)[0]
    assert b"stage-arrow" in path
    assert path.find(b">New<") < path.find(b">Contacted<") < path.find(b">MQL<")
    assert path.find(b">MQL<") < path.find(b">Demo<") < path.find(b">SQL<")
    assert b'aria-current="step"' in path
    assert b"CONTACTED" in detail.content
    assert b'title="Required"' in detail.content
    assert b'data-stages="NURTURING"' in detail.content


def test_deal_close_rules_history_and_open_pipeline(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    owner = make_user("riley")
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = api.post("/api/v1/leads/", lead_form(owner=owner.pk), format="json")
    lead_id = lead.json()["id"]
    open_deal = api.post(
        "/api/v1/deals/",
        deal_form(lead_id, title="Open work", owner=owner.pk),
        format="json",
    )
    lost = api.post(
        "/api/v1/deals/",
        deal_form(lead_id, title="Lost work", amount="50.00"),
        format="json",
    )
    held = api.post(
        "/api/v1/deals/",
        deal_form(lead_id, title="Held work", amount="25.00"),
        format="json",
    )
    won = api.post(
        "/api/v1/deals/",
        deal_form(lead_id, title="Won work", amount=None),
        format="json",
    )
    assert open_deal.status_code == 201
    lost_id = lost.json()["id"]
    no_reason = api.post(
        f"/api/v1/deals/{lost_id}/transition/",
        {"version": 1, "to_stage": "CLOSED_LOST", "reason": "they declined"},
        format="json",
    )
    assert no_reason.status_code == 422
    assert "close_reason" in no_reason.json()
    Deal.objects.filter(pk=lost_id).update(
        stage_entered_at=timezone.now() - timedelta(seconds=240)
    )
    closed = api.post(
        f"/api/v1/deals/{lost_id}/transition/",
        {
            "version": 1,
            "to_stage": "CLOSED_LOST",
            "reason": "they declined",
            "close_reason": "PRICE",
        },
        format="json",
    )
    assert closed.status_code == 200
    assert closed.json()["stage"] == "CLOSED_LOST"
    lost_row = StageHistory.objects.get(object_type="deal", object_id=lost_id)
    assert lost_row.changed_by_id == admin.pk
    assert lost_row.duration_seconds >= 240
    assert lost_row.probability_snapshot == Decimal("0.00")
    assert lost_row.reason == "they declined"
    assert Deal.objects.get(pk=lost_id).outcome == "LOST"

    held_id = held.json()["id"]
    no_hold = api.post(
        f"/api/v1/deals/{held_id}/transition/",
        {"version": 1, "to_stage": "CLOSED_HOLD"},
        format="json",
    )
    assert no_hold.status_code == 422
    held_ok = api.post(
        f"/api/v1/deals/{held_id}/transition/",
        {
            "version": 1,
            "to_stage": "CLOSED_HOLD",
            "close_reason": "CUSTOMER_REQUEST",
            "reason": "customer asked to pause",
        },
        format="json",
    )
    assert held_ok.status_code == 200
    assert Deal.objects.get(pk=held_id).outcome == "HOLD"

    won_id = won.json()["id"]
    with pytest.raises(ValidationError, match="not allowed"):
        transition_deal(
            actor=admin,
            deal_id=won_id,
            version=1,
            to_stage="CLOSED_WON",
        )
    repaired = api.post(
        f"/api/v1/deals/{won_id}/transition/",
        {
            "version": 1,
            "to_stage": "CLOSING",
            "reason": "repair the board",
            "correction": True,
        },
        format="json",
    )
    assert repaired.status_code == 200
    early = api.post(
        f"/api/v1/deals/{won_id}/transition/",
        {"version": 2, "to_stage": "CLOSED_WON"},
        format="json",
    )
    assert early.status_code == 422
    assert "amount" in early.content.decode()
    assert Deal.objects.get(pk=won_id).stage == "CLOSING"
    finished = api.post(
        f"/api/v1/deals/{won_id}/transition/",
        {
            "version": 2,
            "to_stage": "CLOSED_WON",
            "amount": "48000.00",
            "actual_close_date": "2026-12-18",
        },
        format="json",
    )
    assert finished.status_code == 200
    finished_deal = Deal.objects.get(pk=won_id)
    assert finished_deal.outcome == "WON"
    assert str(finished_deal.actual_close_date) == "2026-12-18"
    assert open_pipeline_total(admin) == Decimal("100.00")

    client.force_login(admin)
    listed = client.get(reverse("sales:list"))
    assert b"Open pipeline: $ 100" in listed.content
    assert b"Amount by owner" in listed.content
    board = client.get(reverse("sales:board"))
    assert b"Open work" in board.content
    assert b"Lost work" not in board.content
    assert b"Held work" not in board.content
    assert b"Won work" not in board.content
    detail = client.get(reverse("sales:detail", args=[lost_id]))
    assert b"they declined" in detail.content
    assert b"0%" in detail.content

    client.force_login(owner)
    dragged = client.post(
        reverse("sales:transition", args=[open_deal.json()["id"]]),
        {
            "version": 1,
            "to_stage": "QUALIFIED",
            "reason": "skip ahead",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert dragged.status_code == 422
    assert b"not allowed" in dragged.content
    assert Deal.objects.get(pk=open_deal.json()["id"]).stage == "NEW"


def test_admin_correction_is_reversible_and_audited(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    owner = make_user("riley")
    api = APIClient()
    api.force_authenticate(user=admin)
    created = api.post(
        "/api/v1/leads/",
        lead_form(owner=owner.pk, email="correct@example.test"),
        format="json",
    )
    lead = Lead.objects.get(pk=created.json()["id"])
    with pytest.raises(PermissionDenied):
        transition_lead(
            actor=owner,
            lead_id=lead.pk,
            version=lead.version,
            to_stage="SQL",
            reason="skip the graph",
            correction=True,
        )
    client.force_login(owner)
    denied = client.post(
        reverse("leads:transition", args=[lead.pk]),
        {
            "version": lead.version,
            "to_stage": "SQL",
            "reason": "skip the graph",
            "correction": "1",
        },
    )
    assert denied.status_code == 403
    api.force_authenticate(user=owner)
    denied_api = api.post(
        f"/api/v1/leads/{lead.pk}/transition/",
        {
            "version": lead.version,
            "to_stage": "SQL",
            "reason": "skip the graph",
            "correction": True,
        },
        format="json",
    )
    assert denied_api.status_code == 403
    lead.refresh_from_db()
    assert lead.stage == "NEW"

    api.force_authenticate(user=admin)
    forward = api.post(
        f"/api/v1/leads/{lead.pk}/transition/",
        {
            "version": 1,
            "to_stage": "SQL",
            "reason": "restore a migrated stage",
            "correction": True,
        },
        format="json",
    )
    assert forward.status_code == 200
    backward = api.post(
        f"/api/v1/leads/{lead.pk}/transition/",
        {
            "version": 2,
            "to_stage": "NEW",
            "reason": "put it back",
            "correction": True,
        },
        format="json",
    )
    assert backward.status_code == 200
    assert backward.json()["stage"] == "NEW"
    rows = StageHistory.objects.filter(object_type="lead", object_id=lead.pk)
    assert list(rows.values_list("correction", flat=True)) == [True, True]
    assert (
        AuditEvent.objects.filter(
            action="lead.corrected", object_id=str(lead.pk)
        ).count()
        == 2
    )

    unqualified = api.post(
        f"/api/v1/leads/{lead.pk}/transition/",
        {
            "version": 3,
            "to_stage": "UNQUALIFIED",
            "disqualification_reason": "NO_BUDGET",
        },
        format="json",
    )
    assert unqualified.status_code == 200
    api.force_authenticate(user=owner)
    reopen = api.post(
        f"/api/v1/leads/{lead.pk}/transition/",
        {"version": 4, "to_stage": "NEW", "reason": "it is real"},
        format="json",
    )
    assert reopen.status_code == 403
    assert Lead.objects.get(pk=lead.pk).stage == "UNQUALIFIED"
    api.force_authenticate(user=admin)
    reopened = api.post(
        f"/api/v1/leads/{lead.pk}/transition/",
        {"version": 4, "to_stage": "NEW", "reason": "data was repaired"},
        format="json",
    )
    assert reopened.status_code == 200
    assert reopened.json()["stage"] == "NEW"


def test_retired_targets_and_probability_overrides_are_rejected(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    owner = make_user("riley")
    PicklistValue.objects.filter(list_key="LEAD_STAGE", key="CONTACTED").update(
        active=False
    )
    api = APIClient()
    api.force_authenticate(user=admin)
    created = api.post(
        "/api/v1/leads/",
        lead_form(email="retired@example.test"),
        format="json",
    )
    lead_id = created.json()["id"]
    retired = api.post(
        f"/api/v1/leads/{lead_id}/transition/",
        {
            "version": 1,
            "to_stage": "CONTACTED",
            "contact_substatus": "ATTEMPTED",
            "reason": "called",
        },
        format="json",
    )
    assert retired.status_code == 422
    assert "retired" in retired.content.decode()
    assert Lead.objects.get(pk=lead_id).stage == "NEW"

    lead = api.post(
        "/api/v1/leads/",
        lead_form(owner=owner.pk, email="odds@example.test"),
        format="json",
    )
    deal = api.post(
        "/api/v1/deals/",
        deal_form(lead.json()["id"], title="Odds"),
        format="json",
    )
    deal_id = deal.json()["id"]
    api.force_authenticate(user=owner)
    override = api.post(
        f"/api/v1/deals/{deal_id}/transition/",
        {
            "version": 1,
            "to_stage": "DISCOVERY",
            "reason": "left a message",
            "probability": "80.00",
        },
        format="json",
    )
    assert override.status_code == 403
    assert Deal.objects.get(pk=deal_id).stage == "NEW"
    api.force_authenticate(user=admin)
    missing_reason = api.post(
        f"/api/v1/deals/{deal_id}/transition/",
        {
            "version": 1,
            "to_stage": "DISCOVERY",
            "reason": "left a message",
            "probability": "80.00",
        },
        format="json",
    )
    assert missing_reason.status_code == 422
    assert "probability_reason" in missing_reason.json()
    changed = api.post(
        f"/api/v1/deals/{deal_id}/transition/",
        {
            "version": 1,
            "to_stage": "DISCOVERY",
            "reason": "left a message",
            "probability": "80.00",
            "probability_reason": "executive sponsor is engaged",
        },
        format="json",
    )
    assert changed.status_code == 200
    assert changed.json()["probability"] == "80.00"
    snapshot = StageHistory.objects.get(object_type="deal", object_id=deal_id)
    assert snapshot.probability_snapshot == Decimal("80.00")
    assert snapshot.probability_reason == "executive sponsor is engaged"
    history_api = api.get(f"/api/v1/deals/{deal_id}/stage-history/")
    assert history_api.status_code == 200
    assert history_api.json()[0]["probability_reason"] == "executive sponsor is engaged"
    client.force_login(admin)
    page = client.get(reverse("sales:detail", args=[deal_id]))
    assert b"80%" in page.content
    anonymous = client
    anonymous.logout()
    board = anonymous.get(reverse("leads:board"))
    assert board.status_code == 302
    assert "/login/" in board.url


def _place(record, stage):
    record.stage = stage
    record.stage_entered_at = timezone.now()
    record.save(update_fields=["stage", "stage_entered_at"])
    record.refresh_from_db()


def test_stage_menu_defaults_to_the_next_stage_in_the_cycle():
    assert allowed_targets(DEAL_GRAPH, "NEW")[0] == "DISCOVERY"
    assert allowed_targets(DEAL_GRAPH, "QUALIFIED")[0] == "TECHNICAL_EVALUATION"
    assert allowed_targets(DEAL_GRAPH, "CLOSING")[0] == "CLOSED_WON"
    assert allowed_targets(DEAL_GRAPH, "CLOSED_HOLD")[0] == "NEW"
    assert "CLOSED_HOLD" in allowed_targets(DEAL_GRAPH, "PROPOSAL")
    assert allowed_targets(LEAD_GRAPH, "NEW")[0] == "CONTACTED"
    assert allowed_targets(LEAD_GRAPH, "MQL")[0] == "DEMO_POC"
    assert allowed_targets(LEAD_GRAPH, "SQL")[0] == "NURTURING"
    assert allowed_targets(LEAD_GRAPH, "ARCHIVED")[0] == "NEW"


def test_every_graph_pair_is_enforced_by_the_transition_service():
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    created = api.post("/api/v1/leads/", lead_form(), format="json")
    lead = Lead.objects.get(pk=created.json()["id"])
    follow_up = timezone.now() + timedelta(days=3)
    lead.contact_substatus = "ATTEMPTED"
    lead.nurture_reason = "TIMING"
    lead.disqualification_reason = "NO_BUDGET"
    lead.next_follow_up_at = follow_up
    lead.demo_scheduled_on = follow_up.date()
    lead.technical_contact_name = "Avery Chen"
    lead.notes = "documented"
    lead.save()
    for source, allowed in LEAD_GRAPH.items():
        for destination in LEAD_GRAPH:
            _place(lead, source)
            if destination in allowed:
                moved = transition_lead(
                    actor=admin,
                    lead_id=lead.pk,
                    version=lead.version,
                    to_stage=destination,
                    reason="documented",
                )
                assert moved.stage == destination
            else:
                with pytest.raises(ValidationError):
                    transition_lead(
                        actor=admin,
                        lead_id=lead.pk,
                        version=lead.version,
                        to_stage=destination,
                        reason="documented",
                    )
                lead.refresh_from_db()
                assert lead.stage == source

    deal = api.post(
        "/api/v1/deals/",
        deal_form(lead.pk, title="Graph"),
        format="json",
    )
    record = Deal.objects.get(pk=deal.json()["id"])
    record.amount = Decimal("100.00")
    record.expected_close_date = follow_up.date()
    record.bant_budget_status = "PARTIAL"
    record.bant_authority_status = "PARTIAL"
    record.bant_need_status = "PARTIAL"
    record.bant_timeline_status = "PARTIAL"
    record.close_reason = "PRICE"
    record.evaluation_started_on = follow_up.date()
    record.technical_stakeholder_name = "Priya Shah"
    record.save()
    for source, allowed in DEAL_GRAPH.items():
        for destination in DEAL_GRAPH:
            _place(record, source)
            if destination in allowed:
                close_reason = (
                    "PRICE"
                    if destination == "CLOSED_LOST"
                    else "CUSTOMER_REQUEST"
                    if destination == "CLOSED_HOLD"
                    else ""
                )
                moved = transition_deal(
                    actor=admin,
                    deal_id=record.pk,
                    version=record.version,
                    to_stage=destination,
                    reason="documented",
                    data={"close_reason": close_reason},
                )
                assert moved.stage == destination
            else:
                with pytest.raises(ValidationError):
                    transition_deal(
                        actor=admin,
                        deal_id=record.pk,
                        version=record.version,
                        to_stage=destination,
                        reason="documented",
                    )
                record.refresh_from_db()
                assert record.stage == source


def test_new_records_cannot_bypass_workflow_on_create(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    blocked_lead = api.post(
        "/api/v1/leads/",
        lead_form(stage="SQL"),
        format="json",
    )
    assert blocked_lead.status_code == 422
    assert "stage" in blocked_lead.json()

    lead = api.post("/api/v1/leads/", lead_form(), format="json")
    blocked_deal = api.post(
        "/api/v1/deals/",
        deal_form(lead.json()["id"], stage="PROPOSAL"),
        format="json",
    )
    assert blocked_deal.status_code == 422
    assert "stage" in blocked_deal.json()

    client.force_login(admin)
    injected = client.post(
        reverse("leads:create"),
        lead_form(email="injected@example.test", stage="SQL"),
    )
    assert injected.status_code == 302
    assert Lead.objects.get(email_normalized="injected@example.test").stage == "NEW"


def test_deal_correction_to_open_stage_clears_terminal_state():
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = api.post("/api/v1/leads/", lead_form(), format="json")
    deal = api.post(
        "/api/v1/deals/",
        deal_form(lead.json()["id"], title="Correct outcome"),
        format="json",
    )
    deal_id = deal.json()["id"]
    closed = api.post(
        f"/api/v1/deals/{deal_id}/transition/",
        {
            "version": 1,
            "to_stage": "CLOSED_LOST",
            "close_reason": "PRICE",
            "reason": "entered in error",
        },
        format="json",
    )
    assert closed.status_code == 200
    corrected = api.post(
        f"/api/v1/deals/{deal_id}/transition/",
        {
            "version": 2,
            "to_stage": "PROPOSAL",
            "reason": "restore the open deal",
            "correction": True,
        },
        format="json",
    )
    assert corrected.status_code == 200
    record = Deal.objects.get(pk=deal_id)
    assert record.stage == "PROPOSAL"
    assert record.outcome == ""
    assert record.close_reason == ""
    history = StageHistory.objects.filter(object_type="deal", object_id=deal_id)
    assert history.count() == 2
    assert history.last().correction is True
    assert AuditEvent.objects.filter(
        action="deal.corrected", object_id=str(deal_id)
    ).exists()


def test_stage_history_is_immutable():
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = api.post("/api/v1/leads/", lead_form(), format="json")
    moved = api.post(
        f"/api/v1/leads/{lead.json()['id']}/transition/",
        {
            "version": 1,
            "to_stage": "CONTACTED",
            "reason": "called",
            "contact_substatus": "ATTEMPTED",
        },
        format="json",
    )
    assert moved.status_code == 200
    row = StageHistory.objects.get(object_type="lead", object_id=lead.json()["id"])
    row.reason = "rewritten"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.delete()
    with pytest.raises(ValidationError, match="append-only"):
        StageHistory.objects.filter(pk=row.pk).update(reason="rewritten")
    row.refresh_from_db()
    assert row.reason == "called"


def _lead_transition_data(version, destination):
    return {
        "version": version,
        "to_stage": destination,
        "reason": "documented",
        "contact_substatus": "ATTEMPTED",
        "nurture_reason": "TIMING",
        "disqualification_reason": "NO_BUDGET",
        "demo_scheduled_on": "2026-11-02",
        "technical_contact_name": "Avery Chen",
        "next_follow_up_at": (timezone.now() + timedelta(days=3)).strftime(
            "%Y-%m-%dT%H:%M:%S%z"
        ),
    }


def _deal_transition_data(version, destination):
    close_reason = ""
    if destination == "CLOSED_LOST":
        close_reason = "PRICE"
    elif destination == "CLOSED_HOLD":
        close_reason = "CUSTOMER_REQUEST"
    return {
        "version": version,
        "to_stage": destination,
        "reason": "documented",
        "amount": "100.00",
        "expected_close_date": "2027-01-15",
        "bant_budget_status": "PARTIAL",
        "bant_authority_status": "PARTIAL",
        "bant_need_status": "PARTIAL",
        "bant_timeline_status": "PARTIAL",
        "close_reason": close_reason,
        "evaluation_started_on": "2026-11-02",
        "technical_stakeholder_name": "Priya Shah",
    }


def test_every_graph_pair_is_enforced_by_html_and_api(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    created = api.post("/api/v1/leads/", lead_form(), format="json")
    lead = Lead.objects.get(pk=created.json()["id"])
    lead.contact_substatus = "ATTEMPTED"
    lead.nurture_reason = "TIMING"
    lead.disqualification_reason = "NO_BUDGET"
    lead.next_follow_up_at = timezone.now() + timedelta(days=3)
    lead.demo_scheduled_on = timezone.now().date()
    lead.technical_contact_name = "Avery Chen"
    lead.notes = "documented"
    lead.save()
    client.force_login(admin)

    for source, allowed in LEAD_GRAPH.items():
        for destination in LEAD_GRAPH:
            _place(lead, source)
            response = api.post(
                f"/api/v1/leads/{lead.pk}/transition/",
                _lead_transition_data(lead.version, destination),
                format="json",
            )
            assert response.status_code == (200 if destination in allowed else 422)
            _place(lead, source)
            response = client.post(
                reverse("leads:transition", args=[lead.pk]),
                _lead_transition_data(lead.version, destination),
            )
            assert response.status_code == (302 if destination in allowed else 422)

    deal_response = api.post(
        "/api/v1/deals/",
        deal_form(lead.pk, title="Layer graph"),
        format="json",
    )
    deal = Deal.objects.get(pk=deal_response.json()["id"])
    deal.amount = Decimal("100.00")
    deal.expected_close_date = (timezone.now() + timedelta(days=30)).date()
    deal.bant_budget_status = "PARTIAL"
    deal.bant_authority_status = "PARTIAL"
    deal.bant_need_status = "PARTIAL"
    deal.bant_timeline_status = "PARTIAL"
    deal.evaluation_started_on = timezone.now().date()
    deal.technical_stakeholder_name = "Priya Shah"
    deal.save()
    for source, allowed in DEAL_GRAPH.items():
        for destination in DEAL_GRAPH:
            _place(deal, source)
            response = api.post(
                f"/api/v1/deals/{deal.pk}/transition/",
                _deal_transition_data(deal.version, destination),
                format="json",
            )
            assert response.status_code == (200 if destination in allowed else 422)
            _place(deal, source)
            response = client.post(
                reverse("sales:transition", args=[deal.pk]),
                _deal_transition_data(deal.version, destination),
            )
            assert response.status_code == (302 if destination in allowed else 422)


def test_technical_evaluation_needs_a_start_and_not_a_full_bant_review(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = api.post("/api/v1/leads/", lead_form(), format="json")
    created = api.post(
        "/api/v1/deals/",
        deal_form(lead.json()["id"]),
        format="json",
    )
    deal = Deal.objects.get(pk=created.json()["id"])
    _place(deal, "QUALIFIED")
    with pytest.raises(ValidationError):
        transition_deal(
            actor=admin,
            deal_id=deal.pk,
            version=deal.version,
            to_stage="TECHNICAL_EVALUATION",
            reason="sandbox must pass SSO",
        )
    deal.refresh_from_db()
    moved = transition_deal(
        actor=admin,
        deal_id=deal.pk,
        version=deal.version,
        to_stage="TECHNICAL_EVALUATION",
        reason="sandbox must pass SSO",
        data={
            "evaluation_started_on": "2026-11-02",
            "technical_stakeholder_name": "Priya Shah",
        },
    )
    assert moved.stage == "TECHNICAL_EVALUATION"
    assert str(moved.evaluation_started_on) == "2026-11-02"
    assert moved.technical_stakeholder_name == "Priya Shah"
    assert moved.bant_need_status == "UNKNOWN"
    client.force_login(admin)
    page = client.get(reverse("sales:detail", args=[deal.pk]))
    assert b"POC/Tech Evaluation" in page.content
    assert b"Priya Shah" in page.content
    assert b"Requirements note" in page.content
    assert b'data-stages="CLOSED_LOST"' in page.content
    assert b'name="bant_budget_status"' in page.content
    assert b'name="bant_authority_status"' in page.content
    assert b'name="bant_need_status"' in page.content
    assert b'name="bant_timeline_status"' in page.content
    assert b"no separate approval" in page.content
    editor = client.get(reverse("sales:edit", args=[deal.pk]))
    assert b"Budget" in editor.content
    assert b"Timeline" in editor.content
    assert b"Why the probability changed" in editor.content
    assert b'name="evaluation_started_on"' in editor.content
    dated = update_deal(
        actor=admin,
        deal_id=deal.pk,
        version=moved.version,
        data={"evaluation_started_on": "2026-12-01"},
    )
    assert str(dated.evaluation_started_on) == "2026-12-01"
    deal.refresh_from_db()
    _place(deal, "DISCOVERY")
    qualified = transition_deal(
        actor=admin,
        deal_id=deal.pk,
        version=deal.version,
        to_stage="QUALIFIED",
        data={"amount": "100.00", "expected_close_date": "2027-01-15"},
    )
    assert qualified.stage == "QUALIFIED"
    assert qualified.bant_budget_status == "UNKNOWN"
    recorded = update_deal(
        actor=admin,
        deal_id=deal.pk,
        version=qualified.version,
        data={
            "bant_budget_status": "CONFIRMED",
            "bant_authority_status": "PARTIAL",
            "bant_need_status": "NOT_MET",
            "bant_timeline_status": "UNKNOWN",
        },
    )
    assert recorded.bant_budget_status == "CONFIRMED"
    assert recorded.bant_authority_status == "PARTIAL"
    assert recorded.bant_need_status == "NOT_MET"
    _place(recorded, "PROPOSAL")
    Deal.objects.filter(pk=deal.pk).update(expected_close_date=None)
    deal.refresh_from_db()
    with pytest.raises(ValidationError):
        transition_deal(
            actor=admin,
            deal_id=deal.pk,
            version=deal.version,
            to_stage="NEGOTIATION",
            reason="redlines on the order form",
        )


def test_edit_can_change_probability_when_a_reason_is_given():
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = api.post("/api/v1/leads/", lead_form(), format="json")
    created = api.post(
        "/api/v1/deals/",
        deal_form(lead.json()["id"], title="Odds edit"),
        format="json",
    )
    deal = Deal.objects.get(pk=created.json()["id"])
    with pytest.raises(ValidationError):
        update_deal(
            actor=admin,
            deal_id=deal.pk,
            version=deal.version,
            data={"probability": "55.00"},
        )
    deal.refresh_from_db()
    saved = update_deal(
        actor=admin,
        deal_id=deal.pk,
        version=deal.version,
        data={
            "probability": "55.00",
            "probability_reason": "Sponsor asked for a higher chance",
        },
    )
    assert saved.probability == Decimal("55.00")
    assert saved.confidence == "MEDIUM"
    row = StageHistory.objects.filter(object_type="deal", object_id=deal.pk).get()
    assert row.from_stage == row.to_stage == deal.stage
    assert row.probability_reason == "Sponsor asked for a higher chance"
    unchanged = update_deal(
        actor=admin,
        deal_id=deal.pk,
        version=saved.version,
        data={"probability": "55.00", "notes": "No probability change"},
    )
    assert unchanged.probability == Decimal("55.00")
    assert (
        StageHistory.objects.filter(object_type="deal", object_id=deal.pk).count() == 1
    )


def test_demo_stage_requires_a_date_and_old_stages_are_rewritten():
    import importlib

    from django.apps import apps

    ensure_picklists()
    admin = make_user("ada", admin=True)
    created = APIClient()
    created.force_authenticate(user=admin)
    lead = Lead.objects.get(
        pk=created.post("/api/v1/leads/", lead_form(), format="json").json()["id"]
    )
    _place(lead, "MQL")
    with pytest.raises(ValidationError):
        transition_lead(
            actor=admin,
            lead_id=lead.pk,
            version=lead.version,
            to_stage="DEMO_POC",
            reason="booked",
        )
    lead.refresh_from_db()
    moved = transition_lead(
        actor=admin,
        lead_id=lead.pk,
        version=lead.version,
        to_stage="DEMO_POC",
        reason="booked",
        data={
            "demo_scheduled_on": "2026-11-18",
            "technical_contact_name": "Priya Shah",
        },
    )
    assert moved.stage == "DEMO_POC"
    assert str(moved.demo_scheduled_on) == "2026-11-18"
    assert moved.technical_contact_name == "Priya Shah"
    Lead.objects.filter(pk=lead.pk).update(
        stage="SQL_REACTIVATION",
        nurture_reason="",
        disqualification_reason="NO_AUTHORITY",
    )
    history = StageHistory.objects.create(
        object_type="lead",
        object_id=lead.pk,
        from_stage="SQL_READY",
        to_stage="SQL_REACTIVATION",
        changed_by=admin,
        duration_seconds=0,
        reason="old stage",
    )
    importlib.import_module("core.migrations.0007_lead_stages").apply_lead_stages(
        apps, None
    )
    lead.refresh_from_db()
    history.refresh_from_db()
    assert lead.stage == "NURTURING"
    assert lead.nurture_reason == "REACTIVATION"
    assert lead.disqualification_reason == "WRONG_DECISION_MAKER"
    assert history.from_stage == "SQL"
    assert history.to_stage == "NURTURING"


def test_old_deal_stages_map_without_touching_leads():
    import importlib

    from django.apps import apps

    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = Lead.objects.get(
        pk=api.post("/api/v1/leads/", lead_form(), format="json").json()["id"]
    )
    early = Deal.objects.get(
        pk=api.post(
            "/api/v1/deals/",
            deal_form(lead.pk, title="Early"),
            format="json",
        ).json()["id"]
    )
    later = Deal.objects.get(
        pk=api.post(
            "/api/v1/deals/",
            deal_form(lead.pk, title="Later"),
            format="json",
        ).json()["id"]
    )
    held = Deal.objects.get(
        pk=api.post(
            "/api/v1/deals/",
            deal_form(lead.pk, title="Held"),
            format="json",
        ).json()["id"]
    )
    PicklistValue.objects.update_or_create(
        list_key="DEAL_STAGE",
        key="CONTACTED",
        defaults={"label": "Contacted", "order": 2, "active": True},
    )
    Deal.objects.filter(pk=early.pk).update(stage="CONTACTED")
    Deal.objects.filter(pk=later.pk).update(
        stage="DISCOVERY",
        close_reason="REQUIREMENTS_GAP",
    )
    Deal.objects.filter(pk=held.pk).update(stage="CLOSED_HOLD", close_reason="BUDGET")
    Lead.objects.filter(pk=lead.pk).update(stage="CONTACTED")
    history = StageHistory.objects.create(
        object_type="deal",
        object_id=later.pk,
        from_stage="CONTACTED",
        to_stage="DISCOVERY",
        changed_by=admin,
        duration_seconds=0,
        reason="old path",
    )
    importlib.import_module("core.migrations.0008_deal_stages").apply_deal_stages(
        apps, None
    )
    early.refresh_from_db()
    later.refresh_from_db()
    held.refresh_from_db()
    lead.refresh_from_db()
    history.refresh_from_db()
    assert early.stage == "DISCOVERY"
    assert later.stage == "TECHNICAL_EVALUATION"
    assert later.close_reason == "NO_TECHNICAL_FIT"
    assert held.stage == "CLOSED_HOLD"
    assert held.close_reason == "BUDGET"
    assert lead.stage == "CONTACTED"
    assert history.from_stage == "DISCOVERY"
    assert history.to_stage == "TECHNICAL_EVALUATION"
    assert not PicklistValue.objects.get(list_key="DEAL_STAGE", key="CONTACTED").active
    assert PicklistValue.objects.get(
        list_key="CLOSED_LOST_REASON", key="NO_TECHNICAL_FIT"
    ).active
