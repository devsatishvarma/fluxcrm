import logging
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from audit.models import AuditEvent
from core.services import ensure_roles
from core.taxonomy import ensure_picklists
from identity.models import User
from leads.models import Lead
from leads.seed import seed_phase2
from sales.models import Deal

pytestmark = pytest.mark.django_db


def make_user(username, *, admin=False):
    admin_role, standard = ensure_roles()
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="another-strong-pass",
        display_name=username.title(),
        role=admin_role if admin else standard,
    )


def lead_form(**overrides):
    payload = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company_name": "Analytical Engines",
        "email": "ada@example.test",
        "source": "WEB",
        "stage": "NEW",
        "notes": "private notebook",
    }
    payload.update(overrides)
    return payload


def test_ui_and_api_cover_search_filter_pagination_and_delete(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    client.force_login(admin)
    created = client.post(reverse("leads:create"), lead_form())
    assert created.status_code == 302
    lead = Lead.objects.get(email_normalized="ada@example.test")
    assert AuditEvent.objects.filter(
        action="lead.created", object_id=str(lead.pk)
    ).exists()
    assert "private notebook" not in str(
        AuditEvent.objects.filter(object_id=str(lead.pk)).values_list(
            "after_json", flat=True
        )
    )

    listed = client.get(reverse("leads:list"), {"q": "Analytical", "source": "WEB"})
    assert listed.status_code == 200
    assert b"Analytical Engines" in listed.content
    empty = client.get(reverse("leads:list"), {"q": "zzzz-no-match"})
    assert b"No leads match these filters." in empty.content
    partial = client.get(
        reverse("leads:list"),
        {"q": "Analytical"},
        HTTP_HX_REQUEST="true",
    )
    assert b"<html" not in partial.content.lower()
    assert b"Analytical Engines" in partial.content

    api = APIClient()
    api.force_authenticate(user=admin)
    for index in range(50):
        api.post(
            "/api/v1/leads/",
            {
                "first_name": "Page",
                "last_name": str(index),
                "company_name": f"Paged {index:02d}",
                "source": "OTHER",
                "stage": "NEW",
            },
            format="json",
        )
    page = api.get("/api/v1/leads/?page=2&page_size=50&ordering=company_name")
    assert page.status_code == 200
    assert len(page.json()["results"]) == 1
    too_big = api.get("/api/v1/leads/?page_size=201")
    assert too_big.status_code == 422

    deal = api.post(
        "/api/v1/deals/",
        {
            "title": "Engine rebuild",
            "lead": str(lead.pk),
            "deal_type": "CONSULTING_SERVICES",
            "amount": "1500.00",
            "currency": "USD",
            "temperature": "WARM",
            "stage": "NEW",
            "expected_close_date": "2026-12-01",
        },
        format="json",
    )
    assert deal.status_code == 201
    assert deal.json()["probability"] == "5.00"
    removed = api.delete(
        f"/api/v1/deals/{deal.json()['id']}/",
        {"version": 1, "delete_reason": "Duplicate"},
        format="json",
    )
    assert removed.status_code == 204
    assert api.get(f"/api/v1/deals/{deal.json()['id']}/").status_code == 404

    deleted = client.post(
        reverse("leads:delete", args=[lead.pk]),
        {"version": lead.version, "delete_reason": "Duplicate"},
    )
    assert deleted.status_code == 302
    assert Lead.objects.filter(pk=lead.pk).exists() is False


def test_invalid_values_and_account_links_are_rejected(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    api = APIClient()
    api.force_authenticate(user=admin)
    lead = api.post("/api/v1/leads/", lead_form(), format="json")
    assert lead.status_code == 201
    lead_id = lead.json()["id"]
    orphan = api.post(
        "/api/v1/deals/",
        {
            "title": "Missing lead",
            "deal_type": "CONSULTING_SERVICES",
            "currency": "USD",
            "temperature": "WARM",
            "stage": "NEW",
        },
        format="json",
    )
    assert orphan.status_code == 422
    account_link = api.post(
        "/api/v1/deals/",
        {
            "title": "Account deal",
            "lead": lead_id,
            "account": "northstar",
            "deal_type": "CONSULTING_SERVICES",
            "currency": "USD",
            "temperature": "WARM",
            "stage": "NEW",
        },
        format="json",
    )
    assert account_link.status_code == 422
    assert "account" in account_link.json()
    base = {
        "title": "Bad deal",
        "lead": lead_id,
        "deal_type": "CONSULTING_SERVICES",
        "amount": "10.00",
        "currency": "USD",
        "temperature": "WARM",
        "stage": "NEW",
        "expected_close_date": "2026-12-01",
    }
    cases = {
        "deal_type": {"deal_type": "NOT_A_TYPE"},
        "amount": {"amount": "-1"},
        "currency": {"currency": "EUR"},
        "expected_close_date": {"expected_close_date": "yesterday"},
        "owner": {"owner": 999999},
    }
    for field, replacement in cases.items():
        payload = {**base, **replacement}
        response = api.post("/api/v1/deals/", payload, format="json")
        assert response.status_code == 422
        assert field in response.json()
    bad_stage = api.post(
        "/api/v1/leads/",
        lead_form(stage="NOT_A_STAGE", email="other@example.test"),
        format="json",
    )
    assert bad_stage.status_code == 422


def test_stale_versions_conflict_and_owner_scope_holds(client):
    ensure_picklists()
    admin = make_user("ada", admin=True)
    owner = make_user("riley")
    other = make_user("morgan")
    api = APIClient()
    api.force_authenticate(user=admin)
    created = api.post(
        "/api/v1/leads/",
        lead_form(owner=owner.pk),
        format="json",
    )
    lead_id = created.json()["id"]
    stale = api.patch(
        f"/api/v1/leads/{lead_id}/",
        {"version": 0, "company_name": "Changed"},
        format="json",
    )
    assert stale.status_code == 409
    assert Lead.objects.get(pk=lead_id).company_name == "Analytical Engines"

    owner_api = APIClient()
    owner_api.force_authenticate(user=owner)
    assert owner_api.get(f"/api/v1/leads/{lead_id}/").status_code == 200
    other_api = APIClient()
    other_api.force_authenticate(user=other)
    assert other_api.get(f"/api/v1/leads/{lead_id}/").status_code == 403
    client.force_login(other)
    denied = client.get(reverse("leads:detail", args=[lead_id]))
    assert denied.status_code == 403
    assert other_api.get("/api/v1/leads/?q=Analytical").json()["count"] == 0


def test_seed_values_reconcile_and_lists_do_not_query_per_row(client, caplog):
    ensure_picklists()
    admin = make_user("jordan", admin=True)
    sdr = make_user("morgan")
    created = seed_phase2(actor=admin, sdr=sdr, executive=admin)
    assert "lead-1002" in created
    lead = Lead.objects.get(external_id="lead-1002")
    deal = Deal.objects.get(external_id="deal-2002")
    assert lead.company_name == "Northstar Robotics"
    assert deal.amount == Decimal("12500.00")
    assert deal.lead_id == lead.pk
    client.force_login(admin)
    page = client.get(reverse("leads:detail", args=[lead.pk]))
    assert b"Northstar Robotics" in page.content
    deal_page = client.get(reverse("sales:detail", args=[deal.pk]))
    assert b"12500.00" in deal_page.content
    assert b"Northstar endpoint security renewal" in deal_page.content

    caplog.set_level(logging.INFO)
    client.post(reverse("leads:create"), lead_form(email="notes@example.test"))
    assert "private notebook" not in caplog.text
    assert "notes@example.test" not in caplog.text

    def list_queries():
        with CaptureQueriesContext(connection) as captured:
            response = client.get(reverse("leads:list"))
        assert response.status_code == 200
        return len(captured)

    before = list_queries()
    for index in range(3):
        Lead.objects.create(
            external_id=f"extra-{index}",
            first_name="Extra",
            last_name=str(index),
            company_name=f"Extra Co {index}",
            source="WEB",
            stage="NEW",
            stage_entered_at=lead.stage_entered_at,
            owner=admin,
            created_by=admin,
            updated_by=admin,
        )
    after = list_queries()
    assert before == after


def test_anonymous_visitors_are_sent_to_login(client):
    ensure_picklists()
    make_user("ada", admin=True)
    response = client.get(reverse("leads:list"))
    assert response.status_code == 302
    assert "/login/" in response.url
