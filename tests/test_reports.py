"""Phase 7 report totals, scope, periods, and export audit."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.services import create_account, create_contact
from audit.models import AuditEvent
from core.models import StageHistory
from core.taxonomy import ensure_picklists
from leads.models import Lead
from leads.services import create_lead
from reporting.services import (
    QUERY_BUDGET,
    account_rollups,
    build_report,
    dashboard,
    detail_page,
    local_today,
    report_csv,
)
from sales.models import Deal
from sales.services import confidence_for_probability, create_deal
from tests.test_access import make_user as make_role_user
from tests.test_pipeline import make_user

pytestmark = pytest.mark.django_db


def _lead(actor, company):
    ensure_picklists()
    slug = "".join(character for character in company.lower() if character.isalnum())
    return create_lead(
        actor=actor,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_name": company,
            "source": "WEB",
            "email": f"{slug}@example.test",
        },
        request_id="test",
    )


def _deal(actor, **extra):
    payload = {
        "title": extra.pop("title", "Open work"),
        "deal_type": "CONSULTING_SERVICES",
        "confidence": "MEDIUM",
        "currency": "USD",
        "amount": extra.pop("amount", "10.00"),
    }
    payload.update(extra)
    return create_deal(actor=actor, data=payload, request_id="test")


def test_parent_rollup_counts_each_descendant_deal_once():
    admin = make_user("jordan", admin=True)
    parent = create_account(
        actor=admin,
        data={"name": "Parent Co", "account_type": "CUSTOMER"},
        request_id="test",
    )
    child = create_account(
        actor=admin,
        data={
            "name": "Child Co",
            "account_type": "CUSTOMER",
            "parent": str(parent.pk),
        },
        request_id="test",
    )
    parent_contact = create_contact(
        actor=admin,
        data={
            "first_name": "Pat",
            "last_name": "Parent",
            "email": "pat.parent@example.test",
            "account": str(parent.pk),
        },
        request_id="test",
    )
    child_contact = create_contact(
        actor=admin,
        data={
            "first_name": "Kim",
            "last_name": "Child",
            "email": "kim.child@example.test",
            "account": str(child.pk),
        },
        request_id="test",
    )
    _deal(
        admin,
        title="Parent deal",
        account=str(parent.pk),
        primary_contact=str(parent_contact.pk),
        amount="50.00",
    )
    _deal(
        admin,
        title="Child deal",
        account=str(child.pk),
        primary_contact=str(child_contact.pk),
        amount="100.00",
    )
    rows, company_total = account_rollups(admin)
    by_name = {row["label"]: row for row in rows}
    assert by_name["Parent Co"]["own"] == Decimal("50.00")
    assert by_name["Parent Co"]["rollup"] == Decimal("150.00")
    assert by_name["Child Co"]["rollup"] == Decimal("100.00")
    assert company_total == Decimal("150.00")
    assert sum(row["rollup"] for row in rows) != company_total


def test_reports_stay_inside_viewer_scope():
    owner = make_user("owner")
    other = make_user("other")
    lead = _lead(owner, "Owner Co")
    _deal(owner, lead=str(lead.pk), amount="80.00", title="Owner deal")
    assert dashboard(owner)["open_deals"] == 1
    assert dashboard(owner)["open_pipeline"] == Decimal("80.00")
    assert dashboard(other)["open_deals"] == 0
    assert dashboard(other)["open_pipeline"] == Decimal("0.00")
    assert build_report(other, "leads-by-stage")["total"] == 0


def test_fiscal_quarter_and_viewer_timezone_boundaries():
    admin = make_user("jordan", admin=True)
    assert admin.timezone == "America/Los_Angeles"
    lead = _lead(admin, "Boundary Co")
    _deal(
        admin,
        lead=str(lead.pk),
        amount="10.00",
        title="February close",
        expected_close_date="2026-02-15",
    )
    forecast = build_report(
        admin,
        "forecast",
        {"start": "2026-01-01", "end": "2026-03-31"},
    )
    assert forecast["rows"][0]["label"] == "FY2026 Q1"
    assert forecast["rows"][0]["best"] == Decimal("10.00")
    Lead.objects.filter(pk=lead.pk).update(
        created_at=datetime(2026, 1, 1, 7, 30, tzinfo=UTC)
    )
    january = build_report(
        admin,
        "conversion",
        {"start": "2026-01-01", "end": "2026-01-31"},
    )
    december = build_report(
        admin,
        "conversion",
        {"start": "2025-12-31", "end": "2025-12-31"},
    )
    assert january["total"] == 0
    assert december["total"] == 1


def test_prior_quarter_and_sql_cohort_reconcile():
    admin = make_user("jordan", admin=True)
    current_lead = _lead(admin, "Current Co")
    prior_lead = _lead(admin, "Prior Co")
    current = _deal(
        admin, lead=str(current_lead.pk), amount="60.00", title="Current win"
    )
    prior = _deal(admin, lead=str(prior_lead.pk), amount="40.00", title="Prior win")
    Deal.objects.filter(pk=current.pk).update(
        outcome="WON",
        stage="CLOSED_WON",
        stage_entered_at=datetime(2026, 7, 15, 20, 0, tzinfo=UTC),
        actual_close_date=local_today(admin),
    )
    Deal.objects.filter(pk=prior.pk).update(
        outcome="WON",
        stage="CLOSED_WON",
        stage_entered_at=datetime(2026, 10, 12, 20, 0, tzinfo=UTC),
        actual_close_date=date(2026, 7, 15),
    )
    summary = dashboard(admin)
    assert summary["period_wins"] == Decimal("60.00")
    assert summary["prior_wins"] == Decimal("40.00")
    assert summary["prior_change"] == Decimal("50")
    assert summary["year_wins"] == Decimal("100.00")
    assert summary["prior_year_wins"] == Decimal("0.00")
    assert summary["year_change"] is None
    reached = _lead(admin, "SQL Co")
    missed = _lead(admin, "Missed Co")
    StageHistory.objects.create(
        object_type="lead",
        object_id=reached.pk,
        from_stage="MQL",
        to_stage="SQL",
        changed_by=admin,
    )
    conversion = build_report(
        admin,
        "conversion",
        {"start": "2026-10-01", "end": "2026-12-31"},
    )
    assert conversion["total"] == 4
    assert conversion["sql_count"] == 1
    assert conversion["rows"][2]["count"] == "25%"
    assert missed.company_name == "Missed Co"


def test_detail_rows_are_paginated_and_dashboard_stays_within_budget(client):
    admin = make_user("jordan", admin=True)
    for name in ("One Co", "Two Co", "Three Co"):
        _lead(admin, name)
    page = detail_page(admin, "leads-by-stage", {}, 1, 2)
    assert len(page.object_list) == 2
    assert page.has_next
    assert len(detail_page(admin, "leads-by-stage", {}, 2, 2).object_list) == 1
    client.force_login(admin)
    with CaptureQueriesContext(connection) as captured:
        response = client.get(reverse("reporting:dashboard"))
    assert response.status_code == 200
    assert len(captured) <= QUERY_BUDGET
    assert b"Executive dashboard" in response.content
    assert b"$ 0" in response.content
    labels = (
        b"Open Leads",
        b"Deals Pipeline",
        b"Pipeline Value",
        b"Won this Quarter",
        b"Versus prior quarter",
        b"Won this year",
        b"Versus prior year",
        b"Overdue tasks",
        b"Stale Leads",
    )
    positions = [response.content.find(label) for label in labels]
    assert positions == sorted(positions)
    assert all(position > 0 for position in positions)
    listed = client.get(reverse("reporting:detail", args=["leads-by-stage"]))
    assert b"<table" in listed.content
    assert b"report-chart" in listed.content


def test_deal_pipeline_names_the_company_behind_each_stage():
    admin = make_user("jordan", admin=True)
    lead = _lead(admin, "Boundary Co")
    _deal(admin, lead=str(lead.pk), amount="80.00", title="Boundary renewal")
    report = build_report(admin, "deal-pipeline")
    assert report["rows"][0]["label"] == "New"
    assert report["rows"][0]["companies"] == "Boundary Co ($ 80)"
    assert report["rows"][0]["amount"] == Decimal("80.00")
    assert report["records"][0]["company"] == "Boundary Co"
    assert report["records"][0]["title"] == "Boundary renewal"


def test_blank_forecast_keeps_other_quarters_and_unscheduled_deals(client):
    admin = make_user("jordan", admin=True)
    scheduled = _lead(admin, "Boundary Co")
    unscheduled = _lead(admin, "Open Co")
    _deal(
        admin,
        lead=str(scheduled.pk),
        amount="10.00",
        title="February close",
        expected_close_date="2026-02-15",
    )
    _deal(admin, lead=str(unscheduled.pk), amount="25.00", title="No close date")
    report = build_report(admin, "forecast", {})
    by_label = {row["label"]: row for row in report["rows"]}
    assert by_label["FY2026 Q1"]["best"] == Decimal("10.00")
    assert by_label["FY2026 Q1"]["companies"] == "Boundary Co ($ 10)"
    assert by_label["Unscheduled"]["best"] == Decimal("25.00")
    assert "Open Co" in by_label["Unscheduled"]["companies"]
    client.force_login(admin)
    page = client.get(reverse("reporting:detail", args=["forecast"]))
    assert page.status_code == 200
    assert b"Boundary Co" in page.content
    assert b"FY2026 Q1" in page.content
    assert b"Unscheduled" in page.content
    assert b"Best case" in page.content
    assert b"Open Co" in page.content


def test_report_export_records_actor_filters_fields_and_row_count(client):
    reader = make_user("reader")
    client.force_login(reader)
    denied = client.post(
        reverse("reporting:export", args=["leads-by-stage"]),
        {"fields": ["label"], "start": "2026-01-01", "end": "2026-01-31"},
    )
    assert denied.status_code == 403
    assert not AuditEvent.objects.filter(action="report.exported").exists()
    director = make_role_user("casey", "SALES_DIRECTOR")
    client.force_login(director)
    exported = client.post(
        reverse("reporting:export", args=["leads-by-stage"]),
        {"fields": ["label", "count"], "start": "2026-01-01", "end": "2026-03-31"},
    )
    assert exported.status_code == 200
    assert exported["Content-Type"].startswith("text/csv")
    assert "leads-by-stage.csv" in exported["Content-Disposition"]
    assert b"Lead stage,Companies,Leads,Share" in exported.content
    event = AuditEvent.objects.get(action="report.exported")
    assert event.actor_id == director.pk
    assert event.after_json["filters"] == {
        "start": "2026-01-01",
        "end": "2026-03-31",
    }
    assert event.after_json["fields"] == ["label", "companies", "count", "share"]
    assert event.after_json["row_count"] == 0


def test_contacts_report_lists_people_and_csv_prefixes_formulas(client):
    admin = make_user("jordan", admin=True)
    account = create_account(
        actor=admin,
        data={"name": "Pinecone Health", "account_type": "CUSTOMER"},
        request_id="test",
    )
    create_contact(
        actor=admin,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada.report@example.test",
            "account": str(account.pk),
            "is_primary": True,
        },
        request_id="test",
    )
    report = build_report(admin, "contacts", {})
    assert report["rows"] == [
        {"label": "Pinecone Health", "primary": "Ada Lovelace", "count": 1}
    ]
    assert report["records"][0]["title"] == "Ada Lovelace"
    client.force_login(admin)
    page = client.get(reverse("reporting:detail", args=["contacts"]))
    assert page.status_code == 200
    assert b"Pinecone Health" in page.content
    assert b"Download CSV" in page.content
    exported = client.post(reverse("reporting:export", args=["contacts"]))
    assert exported.status_code == 200
    assert b"Pinecone Health,Ada Lovelace,1" in exported.content
    assert b"Ada Lovelace" in exported.content
    prefixed = report_csv(
        {
            "columns": [("Account", "label")],
            "money_fields": [],
            "rows": [{"label": "=Analytical"}],
            "records": [],
        }
    )
    assert "'=Analytical" in prefixed


def test_confidence_follows_probability_and_deal_reports_are_grouped(client):
    assert confidence_for_probability(Decimal("80")) == "HIGH"
    assert confidence_for_probability(Decimal("79.99")) == "MEDIUM"
    assert confidence_for_probability(Decimal("40")) == "MEDIUM"
    assert confidence_for_probability(Decimal("39.99")) == "LOW"
    admin = make_user("jordan", admin=True)
    lead = _lead(admin, "Confidence Co")
    likely = _deal(
        admin,
        lead=str(lead.pk),
        title="Likely close",
        amount="80.00",
        probability="85.00",
        confidence="LOW",
        expected_close_date="2026-11-15",
    )
    assert likely.confidence == "HIGH"
    early = _deal(
        admin,
        lead=str(lead.pk),
        title="Early work",
        amount="20.00",
        probability="10.00",
    )
    assert early.confidence == "LOW"
    report = build_report(admin, "deals-by-confidence")
    by_label = {row["label"]: row for row in report["rows"]}
    assert list(by_label) == ["High", "Medium", "Low"]
    assert by_label["High"]["count"] == 1
    assert by_label["High"]["amount"] == Decimal("80.00")
    assert by_label["Low"]["count"] == 1
    assert by_label["Medium"]["count"] == 0
    stage = build_report(admin, "deals-by-stage")
    assert stage["rows"][0]["label"] == "New"
    assert stage["rows"][0]["count"] == 2
    assert [label for label, _key in stage["record_columns"]] == [
        "Company",
        "Deal title",
        "Deal stage",
        "Amount",
    ]
    assert [label for label, _key in stage["columns"]][0] == "Deal stage"
    quarter = build_report(admin, "deals-by-quarter")
    assert {row["label"] for row in quarter["rows"]} == {"FY2026 Q4", "Unscheduled"}
    owners = build_report(admin, "deals-by-owner")
    assert owners["rows"][0]["label"] == admin.display_name
    assert owners["rows"][0]["count"] == 2
    aging = build_report(admin, "deals-by-age")
    assert aging["rows"][0]["label"] == "0–7 days"
    assert aging["rows"][0]["count"] == 2
    client.force_login(admin)
    page = client.get(reverse("sales:list"))
    text = page.content.decode()
    assert "Pipeline" in text
    assert "Deals by stage" in text
    assert "Deals by confidence" in text
    assert "Timing" in text
    assert "Deals by age" in text
    assert "Deals by quarter" in text
    assert "Ownership" in text
    assert "Deals by sales owner" in text
    form = client.get(reverse("sales:create"))
    assert b'name="confidence"' not in form.content
    assert b"Win probability" in form.content
    reports = client.get(reverse("reporting:dashboard"))
    body = reports.content.decode()
    assert "Deals by confidence" in body
    assert body.index("Leads") < body.index("Deals by stage")
