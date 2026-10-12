"""Phase 5 account, contact, and conversion gates."""

import threading
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.conversion import ConversionChoiceRequired, convert_lead
from accounts.models import Account, Contact
from accounts.services import (
    create_account,
    create_contact,
    mark_primary,
    set_account_parent,
    set_reports_to,
)
from activities.models import Activity
from audit.models import AuditEvent
from core.models import StageHistory
from core.services import ensure_roles
from core.taxonomy import ensure_picklists
from identity.models import User
from leads.services import create_lead
from sales.models import Deal
from sales.services import create_deal, deal_history, transition_deal

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


def make_lead(actor, **overrides):
    ensure_picklists()
    payload = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company_name": "Analytical Engines",
        "email": "ada@example.test",
        "website_url": "https://analytical.example",
        "source": "WEB",
        "stage": "NEW",
    }
    payload.update(overrides)
    return create_lead(actor=actor, data=payload)


def test_account_and_contact_hierarchies_cannot_cycle():
    user = make_user("owner")
    parent = create_account(
        actor=user, data={"name": "Parent Co", "account_type": "CUSTOMER"}
    )
    child = create_account(
        actor=user,
        data={"name": "Child Co", "account_type": "PROSPECT", "parent": parent.pk},
    )
    with pytest.raises(ValidationError):
        set_account_parent(actor=user, account=parent, parent_id=parent.pk)
    with pytest.raises(ValidationError):
        set_account_parent(actor=user, account=parent, parent_id=child.pk)

    boss = create_contact(
        actor=user,
        data={"first_name": "Bo", "last_name": "Boss", "account": parent.pk},
    )
    report = create_contact(
        actor=user,
        data={
            "first_name": "Ri",
            "last_name": "Report",
            "account": parent.pk,
            "reports_to": boss.pk,
        },
    )
    with pytest.raises(ValidationError):
        set_reports_to(actor=user, contact=boss, manager_id=report.pk)
    other = create_account(
        actor=user, data={"name": "Other Co", "account_type": "PARTNER"}
    )
    outsider = create_contact(
        actor=user,
        data={"first_name": "Out", "last_name": "Side", "account": other.pk},
    )
    with pytest.raises(ValidationError):
        set_reports_to(actor=user, contact=report, manager_id=outsider.pk)
    admin = make_user("admin", admin=True)
    set_reports_to(actor=admin, contact=report, manager_id=outsider.pk)
    assert Contact.objects.get(pk=report.pk).reports_to_id == outsider.pk


@pytest.mark.django_db(transaction=True)
def test_one_primary_contact_under_concurrent_requests():
    user = make_user("primary")
    account = create_account(
        actor=user, data={"name": "Primary Co", "account_type": "CUSTOMER"}
    )
    first = create_contact(
        actor=user,
        data={"first_name": "Ann", "last_name": "One", "account": account.pk},
    )
    second = create_contact(
        actor=user,
        data={"first_name": "Bea", "last_name": "Two", "account": account.pk},
    )
    barrier = threading.Barrier(2)
    errors = []

    def choose(contact):
        try:
            barrier.wait(timeout=5)
            mark_primary(actor=user, contact=contact)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [
        threading.Thread(target=choose, args=(first,)),
        threading.Thread(target=choose, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert Contact.objects.filter(account=account, is_primary=True).count() == 1


def test_duplicate_candidates_require_an_explicit_choice():
    user = make_user("match")
    create_account(
        actor=user,
        data={
            "name": "Northstar Robotics",
            "account_type": "PROSPECT",
            "website_url": "https://northstar.example",
        },
    )
    lead = make_lead(
        user,
        company_name="Northstar",
        website_url="https://northstar.example",
        email="new@northstar.example",
    )
    with pytest.raises(ConversionChoiceRequired) as choice:
        convert_lead(
            actor=user,
            lead_id=lead.pk,
            version=lead.version,
            data={"account_mode": "create", "deal_action": "leave"},
        )
    reasons = choice.value.payload["account_candidates"][0]["reasons"]
    assert "Same website domain" in reasons
    assert "Similar account name" in reasons
    assert Account.objects.count() == 1

    created = convert_lead(
        actor=user,
        lead_id=lead.pk,
        version=lead.version,
        data={
            "account_mode": "create",
            "confirm_new": "1",
            "justification": "A different Northstar legal entity",
            "deal_action": "leave",
        },
    )
    assert created["idempotent"] is False
    assert Account.objects.count() == 2


def test_duplicate_conversion_submissions_are_idempotent():
    user = make_user("once")
    lead = make_lead(user)
    first = convert_lead(
        actor=user,
        lead_id=lead.pk,
        version=lead.version,
        data={"deal_action": "leave"},
    )
    second = convert_lead(
        actor=user,
        lead_id=lead.pk,
        version=1,
        data={"account_name": "A second company", "deal_action": "create"},
    )
    assert second["idempotent"] is True
    assert second["account_id"] == first["account_id"]
    assert Account.objects.count() == 1
    assert Contact.objects.count() == 1


def test_injected_failure_leaves_no_partial_state():
    user = make_user("rollback")
    lead = make_lead(user)
    deal = create_deal(
        actor=user,
        data={
            "title": "Open work",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "10.00",
            "currency": "USD",
            "confidence": "MEDIUM",
            "stage": "NEW",
        },
    )
    with pytest.raises(RuntimeError, match="injected"):
        convert_lead(
            actor=user,
            lead_id=lead.pk,
            version=lead.version,
            data={"deal_action": "reparent"},
            fail_at="after_contact",
        )
    lead.refresh_from_db()
    deal.refresh_from_db()
    assert lead.converted_at is None
    assert Account.objects.count() == 0
    assert Contact.objects.count() == 0
    assert deal.lead_id == lead.pk
    assert deal.account_id is None


def test_reparented_deals_keep_values_and_history():
    user = make_user("deals")
    lead = make_lead(user)
    open_deal = create_deal(
        actor=user,
        data={
            "title": "Open work",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "12500.00",
            "currency": "USD",
            "confidence": "MEDIUM",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=user,
        deal_id=open_deal.pk,
        version=open_deal.version,
        to_stage="CONTACTED",
        reason="Introduced the team",
    )
    history_before = list(deal_history(open_deal).values_list("to_stage", "reason"))
    amount = open_deal.amount
    stage_before = lead.stage
    convert_lead(
        actor=user,
        lead_id=lead.pk,
        version=lead.version,
        data={"deal_action": "reparent"},
    )
    open_deal.refresh_from_db()
    lead.refresh_from_db()
    assert open_deal.lead_id is None
    assert open_deal.account_id is not None
    assert open_deal.converted_from_lead_id == lead.pk
    assert open_deal.stage == "CONTACTED"
    assert open_deal.amount == amount
    assert lead.stage == stage_before
    assert list(deal_history(open_deal).values_list("to_stage", "reason")) == (
        history_before
    )
    assert StageHistory.objects.filter(object_id=open_deal.pk).count() == len(
        history_before
    )


def test_conversion_permissions_links_timeline_and_audit(client):
    owner = make_user("owner2")
    other = make_user("other")
    admin = make_user("boss", admin=True)
    lead = make_lead(owner)
    partner = create_account(
        actor=admin,
        data={"name": "Partner Co", "account_type": "PARTNER", "owner": owner.pk},
    )
    with pytest.raises(PermissionDenied):
        convert_lead(
            actor=owner,
            lead_id=lead.pk,
            version=lead.version,
            data={
                "account_mode": "existing",
                "account_id": partner.pk,
                "deal_action": "leave",
            },
        )
    api = APIClient()
    api.force_authenticate(user=other)
    denied = api.post(
        f"/api/v1/leads/{lead.pk}/convert/",
        {"version": lead.version, "deal_action": "leave"},
        format="json",
    )
    assert denied.status_code == 403

    result = convert_lead(
        actor=admin,
        lead_id=lead.pk,
        version=lead.version,
        data={
            "account_mode": "existing",
            "account_id": partner.pk,
            "deal_action": "leave",
        },
    )
    lead.refresh_from_db()
    contact = Contact.objects.get(pk=result["contact_id"])
    assert lead.converted_account_id == partner.pk
    assert lead.converted_contact_id == contact.pk
    assert contact.converted_from_lead_id == lead.pk
    assert contact.account_id == partner.pk
    assert Activity.objects.filter(subject="Lead converted").count() == 1
    assert AuditEvent.objects.filter(
        action="lead.converted", object_id=str(lead.pk)
    ).exists()
    audit = AuditEvent.objects.get(action="lead.converted", object_id=str(lead.pk))
    assert "ada@example.test" not in str(audit.after_json)

    client.force_login(owner)
    active = client.get(reverse("leads:list"))
    assert b"Analytical Engines" not in active.content
    converted = client.get(reverse("leads:list"), {"converted": "1"})
    assert b"Analytical Engines" in converted.content
    detail = client.get(reverse("accounts:detail", args=[partner.pk]))
    assert detail.status_code == 200
    assert b"Lead converted" in detail.content


def test_existing_contact_fields_are_not_overwritten_silently():
    user = make_user("fields")
    account = create_account(
        actor=user, data={"name": "Field Co", "account_type": "CUSTOMER"}
    )
    contact = create_contact(
        actor=user,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "kept@example.test",
            "title": "Engineer",
            "account": account.pk,
        },
    )
    lead = make_lead(
        user,
        company_name="Field Co",
        email="ada@example.test",
        title="Engineer",
        website_url="",
    )
    with pytest.raises(ConversionChoiceRequired) as choice:
        convert_lead(
            actor=user,
            lead_id=lead.pk,
            version=lead.version,
            data={
                "account_mode": "existing",
                "account_id": account.pk,
                "contact_mode": "existing",
                "contact_id": contact.pk,
                "deal_action": "leave",
            },
        )
    assert choice.value.payload["differences"][0]["field"] == "email"
    contact.refresh_from_db()
    assert contact.email == "kept@example.test"

    convert_lead(
        actor=user,
        lead_id=lead.pk,
        version=lead.version,
        data={
            "account_mode": "existing",
            "account_id": account.pk,
            "contact_mode": "existing",
            "contact_id": contact.pk,
            "field_choices": {"email": "keep"},
            "deal_action": "leave",
        },
    )
    contact.refresh_from_db()
    assert contact.email == "kept@example.test"


def test_convert_page_shows_candidates_and_can_create(client):
    user = make_user("page")
    create_account(
        actor=user,
        data={"name": "Analytical Engines", "account_type": "PROSPECT"},
    )
    lead = make_lead(user, website_url="")
    client.force_login(user)
    blocked = client.post(
        reverse("leads:convert", args=[lead.pk]),
        {"version": lead.version, "account_mode": "create", "deal_action": "leave"},
    )
    assert blocked.status_code == 422
    assert b"Same account name" in blocked.content
    assert Account.objects.count() == 1
    saved = client.post(
        reverse("leads:convert", args=[lead.pk]),
        {
            "version": lead.version,
            "account_mode": "create",
            "confirm_new": "1",
            "justification": "Separate division",
            "account_type": "PROSPECT",
            "deal_action": "create",
            "contact_mode": "create",
        },
    )
    assert saved.status_code == 302
    assert Account.objects.count() == 2
    assert Deal.objects.filter(account__isnull=False, lead__isnull=True).count() == 1
    listed = client.get(reverse("accounts:list"))
    assert b"Analytical Engines" in listed.content


def test_lead_and_deal_stages_move_independently(client):
    user = make_user("stages")
    lead = make_lead(user)
    deal = create_deal(
        actor=user,
        data={
            "title": "Separate work",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "10.00",
            "currency": "USD",
            "confidence": "MEDIUM",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=user,
        deal_id=deal.pk,
        version=deal.version,
        to_stage="CONTACTED",
        reason="Called the buyer",
    )
    lead.refresh_from_db()
    deal.refresh_from_db()
    assert deal.stage == "CONTACTED"
    assert lead.stage == "NEW"
    assert lead.converted_at is None
    assert Account.objects.count() == 0
    from leads.services import transition_lead

    transition_lead(
        actor=user,
        lead_id=lead.pk,
        version=lead.version,
        to_stage="CONTACTED",
        reason="Reached them",
        data={"contact_substatus": "ATTEMPTED"},
    )
    lead.refresh_from_db()
    deal.refresh_from_db()
    assert lead.stage == "CONTACTED"
    assert deal.stage == "CONTACTED"
    assert Account.objects.count() == 0
    client.force_login(user)
    lead_page = client.get(reverse("leads:detail", args=[lead.pk]))
    deal_page = client.get(reverse("sales:detail", args=[deal.pk]))
    assert b"Move lead stage" in lead_page.content
    assert b"Move deal stage" not in lead_page.content
    assert b"Move deal stage" in deal_page.content
    assert b"Move lead stage" not in deal_page.content


def test_closing_a_deal_converts_the_lead_without_changing_its_stage(client):
    user = make_user("close")
    lead = make_lead(user, website_url="https://analytical.example")
    sibling = create_deal(
        actor=user,
        data={
            "title": "Still open",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "5.00",
            "currency": "USD",
            "confidence": "LOW",
            "stage": "NEW",
        },
    )
    held = create_deal(
        actor=user,
        data={
            "title": "Paused",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "8.00",
            "currency": "USD",
            "confidence": "LOW",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=user,
        deal_id=held.pk,
        version=held.version,
        to_stage="CLOSED_HOLD",
        reason="Pause",
        data={"close_reason": "CUSTOMER_REQUEST"},
    )
    held.refresh_from_db()
    lead.refresh_from_db()
    assert held.stage == "CLOSED_HOLD"
    assert held.lead_id == lead.pk
    assert lead.converted_at is None
    assert Account.objects.count() == 0

    won = create_deal(
        actor=user,
        data={
            "title": "Won work",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "48000.00",
            "currency": "USD",
            "confidence": "HIGH",
            "stage": "NEW",
        },
    )
    history_before = list(deal_history(won).values_list("to_stage", "reason"))
    transition_deal(
        actor=user,
        deal_id=won.pk,
        version=won.version,
        to_stage="CLOSED_LOST",
        reason="Signed then lost",
        data={"close_reason": "PRICE"},
    )
    won.refresh_from_db()
    lead.refresh_from_db()
    sibling.refresh_from_db()
    assert lead.stage == "NEW"
    assert won.stage == "CLOSED_LOST"
    assert won.amount == Decimal("48000.00")
    assert won.lead_id is None
    assert won.converted_from_lead_id == lead.pk
    rows = list(deal_history(won).values_list("to_stage", "reason"))
    assert rows == history_before + [("CLOSED_LOST", "Signed then lost")]
    account = Account.objects.get()
    assert account.name == "Analytical Engines"
    assert account.account_type == "PROSPECT"
    assert account.website_domain == "analytical.example"
    assert lead.converted_account_id == account.pk
    contact = Contact.objects.get(account=account)
    assert contact.email == "ada@example.test"
    assert contact.converted_from_lead_id == lead.pk
    assert sibling.lead_id == lead.pk
    assert sibling.stage == "NEW"
    assert Activity.objects.filter(subject="Lead converted").count() == 1
    client.force_login(user)
    account_page = client.get(reverse("accounts:detail", args=[account.pk]))
    assert account_page.status_code == 200
    assert b"Ada Lovelace" in account_page.content
    assert b"ada@example.test" in account_page.content
    contacts_page = client.get(reverse("accounts:contacts"))
    assert b"Ada Lovelace" in contacts_page.content
    assert b"Analytical Engines" in contacts_page.content
    lead_page = client.get(reverse("leads:list"))
    assert b"Ada Lovelace" not in lead_page.content
    deal_page = client.get(reverse("sales:detail", args=[won.pk]))
    assert b"Ada Lovelace" in deal_page.content

    admin = make_user("closer", admin=True)
    won_lead = make_lead(
        admin,
        first_name="Lin",
        last_name="Won",
        company_name="Won Co",
        email="lin@won.example",
        website_url="https://won.example",
    )
    won_deal = create_deal(
        actor=admin,
        data={
            "title": "Actual win",
            "lead": won_lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "100.00",
            "currency": "USD",
            "confidence": "HIGH",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=admin,
        deal_id=won_deal.pk,
        version=won_deal.version,
        to_stage="CLOSED_WON",
        reason="Signed",
        correction=True,
        data={"expected_close_date": "2026-12-18"},
    )
    won_lead.refresh_from_db()
    assert won_lead.stage == "NEW"
    assert Account.objects.get(name="Won Co").account_type == "CUSTOMER"

    lost = create_deal(
        actor=user,
        data={
            "title": "Later loss",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "20.00",
            "currency": "USD",
            "confidence": "LOW",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=user,
        deal_id=lost.pk,
        version=lost.version,
        to_stage="CLOSED_LOST",
        reason="Price",
        data={"close_reason": "PRICE"},
    )
    lost.refresh_from_db()
    assert lost.account_id == account.pk
    assert lost.lead_id is None
    assert Account.objects.count() == 2
    assert Contact.objects.filter(account=account).count() == 1


def test_closed_deal_uses_an_exact_account_and_ignores_a_similar_name():
    user = make_user("matchclose")
    existing = create_account(
        actor=user,
        data={
            "name": "Analytical Engines",
            "account_type": "PARTNER",
            "website_url": "https://analytical.example",
        },
    )
    create_contact(
        actor=user,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.test",
            "title": "Kept title",
            "account": existing.pk,
        },
    )
    lead = make_lead(user, title="New title", website_url="https://analytical.example")
    deal = create_deal(
        actor=user,
        data={
            "title": "Lost work",
            "lead": lead.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "15.00",
            "currency": "USD",
            "confidence": "LOW",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=user,
        deal_id=deal.pk,
        version=deal.version,
        to_stage="CLOSED_LOST",
        reason="No budget",
        data={"close_reason": "PRICE"},
    )
    deal.refresh_from_db()
    existing.refresh_from_db()
    contact = Contact.objects.get(email_normalized="ada@example.test")
    assert Account.objects.count() == 1
    assert deal.account_id == existing.pk
    assert existing.account_type == "PARTNER"
    assert contact.title == "Kept title"
    assert Contact.objects.count() == 1

    other = make_lead(
        user,
        first_name="Grace",
        last_name="Hopper",
        company_name="Northstar",
        email="grace@northstar.example",
        website_url="https://other.example",
    )
    create_account(
        actor=user,
        data={"name": "Northstar Robotics", "account_type": "PROSPECT"},
    )
    fuzzy = create_deal(
        actor=user,
        data={
            "title": "Fuzzy",
            "lead": other.pk,
            "deal_type": "CONSULTING_SERVICES",
            "amount": "9.00",
            "currency": "USD",
            "confidence": "MEDIUM",
            "stage": "NEW",
        },
    )
    transition_deal(
        actor=user,
        deal_id=fuzzy.pk,
        version=fuzzy.version,
        to_stage="CLOSED_LOST",
        reason="Not this company",
        data={"close_reason": "PRICE"},
    )
    fuzzy.refresh_from_db()
    created = Account.objects.get(name="Northstar")
    assert created.pk != Account.objects.get(name="Northstar Robotics").pk
    assert created.account_type == "PROSPECT"
    assert fuzzy.account_id == created.pk
    assert Contact.objects.filter(
        account=created, email="grace@northstar.example"
    ).exists()


def test_contacts_page_is_in_the_nav_and_groups_by_account(client):
    user = make_user("directory")
    alpha = create_account(
        actor=user, data={"name": "Alpha Co", "account_type": "CUSTOMER"}
    )
    beta = create_account(
        actor=user, data={"name": "Beta Co", "account_type": "PROSPECT"}
    )
    create_contact(
        actor=user,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@alpha.example",
            "title": "Engineer",
            "account": alpha.pk,
            "is_primary": "1",
        },
    )
    create_contact(
        actor=user,
        data={
            "first_name": "Grace",
            "last_name": "Hopper",
            "email": "grace@beta.example",
            "account": beta.pk,
        },
    )
    client.force_login(user)
    page = client.get(reverse("accounts:contacts"))
    assert page.status_code == 200
    body = page.content
    assert b'href="/contacts/"' in body
    groups = body.split(b"<section", 1)[1]
    assert groups.find(b"Alpha Co") < groups.find(b"Ada Lovelace")
    assert groups.find(b"Ada Lovelace") < groups.find(b"Beta Co")
    assert groups.find(b"Beta Co") < groups.find(b"Grace Hopper")
    filtered = client.get(
        reverse("accounts:contacts"),
        {"q": "Engineer", "account": str(alpha.pk), "primary": "1"},
    )
    assert b"Ada Lovelace" in filtered.content
    assert b"Grace Hopper" not in filtered.content
    results = filtered.content.split(b"<section", 1)[1]
    assert b"Alpha Co" in results
    assert b"Beta Co" not in results
