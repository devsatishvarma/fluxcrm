"""Idempotent Phase 2 leads and lead-linked deals."""

from datetime import date
from decimal import Decimal

from django.utils.dateparse import parse_datetime

from core.taxonomy import ensure_picklists
from leads.models import Lead
from leads.services import create_lead, transition_lead
from sales.models import Deal
from sales.services import create_deal, transition_deal

LEADS = (
    {
        "external_id": "lead-1001",
        "first_name": "Jamie",
        "last_name": "Ng",
        "company_name": "Pinecone Health Group",
        "email": "jamie.ng@example.test",
        "source": "WEB",
        "rating": "HOT",
        "stage": "MQL",
        "industry": "HEALTHCARE",
        "company_size_band": "201_500",
        "employee_count": 320,
        "owner_slot": "sdr",
    },
    {
        "external_id": "lead-1002",
        "first_name": "Alex",
        "last_name": "Wong",
        "company_name": "Northstar Robotics",
        "email": "alex.wong@example.test",
        "source": "REFERRAL",
        "rating": "WARM",
        "stage": "SQL_READY",
        "industry": "MANUFACTURING",
        "owner_slot": "executive",
    },
    {
        "external_id": "lead-1003",
        "first_name": "Drew",
        "last_name": "Singh",
        "company_name": "Example Unknown Co",
        "email": "drew.singh@example.test",
        "source": "CONFERENCE_EVENT",
        "rating": "WARM",
        "stage": "NURTURING",
        "nurture_reason": "MQL_NOT_SALES_READY",
        "next_follow_up_at": parse_datetime("2026-11-15T18:00:00+00:00"),
        "owner_slot": "sdr",
    },
    {
        "external_id": "lead-1004",
        "first_name": "Casey",
        "last_name": "Morgan",
        "company_name": "Pinecone Health Group",
        "email": "casey.morgan@example.test",
        "source": "PARTNER",
        "rating": "COLD",
        "stage": "CONTACTED",
        "contact_substatus": "IN_CONTACT",
        "owner_slot": "executive",
    },
    {
        "external_id": "lead-1005",
        "first_name": "Robin",
        "last_name": "Fox",
        "company_name": "Bad Data Example",
        "source": "LIST_PURCHASE",
        "rating": "COLD",
        "stage": "UNQUALIFIED",
        "disqualification_reason": "BAD_DATA",
        "owner_slot": "sdr",
    },
)

DEALS = (
    {
        "external_id": "deal-2002",
        "title": "Northstar endpoint security renewal",
        "lead_external_id": "lead-1002",
        "deal_type": "OEM_RESALE",
        "amount": Decimal("12500.00"),
        "currency": "USD",
        "confidence": "MEDIUM",
        "stage": "PROPOSAL",
        "expected_close_date": date(2027, 2, 15),
        "owner_slot": "executive",
    },
    {
        "external_id": "deal-2004",
        "title": "Pinecone security assessment",
        "lead_external_id": "lead-1001",
        "deal_type": "CONSULTING_SERVICES",
        "amount": Decimal("48000.00"),
        "currency": "USD",
        "confidence": "HIGH",
        "stage": "DISCOVERY",
        "expected_close_date": date(2026, 12, 18),
        "owner_slot": "executive",
    },
)


def seed_phase2(*, actor, sdr, executive):
    """Create the known synthetic scenario once. Existing IDs are left unchanged."""
    ensure_picklists()
    owners = {"sdr": sdr, "executive": executive}
    created = []
    for spec in LEADS:
        if Lead.all_objects.filter(external_id=spec["external_id"]).exists():
            continue
        payload = {key: value for key, value in spec.items() if key != "owner_slot"}
        payload["owner"] = owners[spec["owner_slot"]].pk
        target_stage = payload["stage"]
        payload["stage"] = "NEW"
        lead = create_lead(actor=actor, data=payload, request_id="seed")
        if target_stage != "NEW":
            transition_lead(
                actor=actor,
                lead_id=lead.pk,
                version=lead.version,
                to_stage=target_stage,
                reason="Synthetic fixture stage",
                correction=True,
                request_id="seed",
            )
        created.append(spec["external_id"])
    for spec in DEALS:
        if Deal.all_objects.filter(external_id=spec["external_id"]).exists():
            continue
        lead = Lead.objects.get(external_id=spec["lead_external_id"])
        payload = {
            key: value
            for key, value in spec.items()
            if key not in {"owner_slot", "lead_external_id"}
        }
        payload["lead"] = lead.pk
        payload["owner"] = owners[spec["owner_slot"]].pk
        payload["expected_close_date"] = spec["expected_close_date"].isoformat()
        target_stage = payload["stage"]
        payload["stage"] = "NEW"
        deal = create_deal(actor=actor, data=payload, request_id="seed")
        if target_stage != "NEW":
            transition_deal(
                actor=actor,
                deal_id=deal.pk,
                version=deal.version,
                to_stage=target_stage,
                reason="Synthetic fixture stage",
                correction=True,
                request_id="seed",
            )
        created.append(spec["external_id"])
    return created
