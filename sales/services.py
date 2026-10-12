"""Lead-linked deal list, change, and audit operations."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from audit.models import AuditEvent
from core.access import get_scoped, scoped
from core.exceptions import VersionConflict
from core.taxonomy import DEAL_STAGE_PROBABILITY
from core.validation import (
    clean_currency,
    clean_date,
    clean_delete_reason,
    clean_external_id,
    clean_known_key,
    clean_money,
    clean_owner,
    clean_required_key,
    require_version,
)
from leads.models import Lead
from sales.models import Deal

logger = logging.getLogger(__name__)

DEAL_ORDERING = {
    "created_at": "created_at",
    "-created_at": "-created_at",
    "updated_at": "updated_at",
    "-updated_at": "-updated_at",
    "title": "title",
    "-title": "-title",
    "amount": "amount",
    "-amount": "-amount",
    "expected_close_date": "expected_close_date",
    "-expected_close_date": "-expected_close_date",
    "stage": "stage",
    "-stage": "-stage",
}


def deal_snapshot(deal: Deal) -> dict:
    return {
        "external_id": deal.external_id,
        "title": deal.title,
        "lead_id": str(deal.lead_id),
        "stage": deal.stage,
        "deal_type": deal.deal_type,
        "amount": None if deal.amount is None else str(deal.amount),
        "currency": deal.currency,
        "owner_id": deal.owner_id,
        "version": deal.version,
        "deleted": deal.deleted_at is not None,
    }


def _record(actor, action, deal, before, request_id):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type="sales.deal",
        object_id=str(deal.pk),
        before_json=before,
        after_json=deal_snapshot(deal),
        request_id=request_id,
        source="web",
    )
    logger.info(action, extra={"object_id": str(deal.pk), "outcome": "success"})


def _visible_lead(actor, lead_id):
    if not lead_id:
        raise ValidationError({"lead": "A deal must belong to a lead."})
    try:
        return get_scoped(Lead, actor, lead_id)
    except PermissionDenied as exc:
        raise ValidationError({"lead": "You do not have access to that lead."}) from exc
    except Http404 as exc:
        raise ValidationError({"lead": "Select an active lead."}) from exc


def _probability(stage, value):
    if value in (None, ""):
        return Decimal(DEAL_STAGE_PROBABILITY[stage])
    amount = clean_money(value, "probability")
    if amount is None or amount > Decimal("100.00"):
        raise ValidationError({"probability": "Enter a probability from 0 to 100."})
    return amount


def normalize_deal(actor, data, *, current=None):
    if "account" in data and data.get("account") not in (None, ""):
        raise ValidationError(
            {"account": "Deals cannot be linked to an account before Phase 5."}
        )
    partial = current is not None
    normalized = {}
    if not partial or "external_id" in data:
        normalized["external_id"] = clean_external_id(
            data.get("external_id"),
            current=None if current is None else current.external_id,
        )
    if not partial or "title" in data:
        title = str(
            data.get("title", "" if current is None else current.title) or ""
        ).strip()
        if not title:
            raise ValidationError({"title": "This field is required."})
        if len(title) > 200:
            raise ValidationError({"title": "Use 200 characters or fewer."})
        normalized["title"] = title
    if not partial or "lead" in data:
        lead_value = data.get("lead", None if current is None else current.lead_id)
        normalized["lead"] = _visible_lead(actor, lead_value)
    if not partial or "deal_type" in data:
        normalized["deal_type"] = clean_required_key(
            "DEAL_TYPE",
            data.get("deal_type", "" if current is None else current.deal_type),
            "deal_type",
        )
    if not partial or "stage" in data:
        normalized["stage"] = clean_required_key(
            "DEAL_STAGE",
            data.get("stage", "" if current is None else current.stage),
            "stage",
        )
    if not partial or "temperature" in data:
        normalized["temperature"] = clean_required_key(
            "TEMPERATURE",
            data.get("temperature", "" if current is None else current.temperature),
            "temperature",
        )
    if not partial or "currency" in data:
        normalized["currency"] = clean_currency(
            data.get("currency", "USD" if current is None else current.currency)
        )
    if not partial or "amount" in data:
        normalized["amount"] = clean_money(
            data.get("amount", None if current is None else current.amount)
        )
    if not partial or "expected_close_date" in data:
        normalized["expected_close_date"] = clean_date(
            data.get(
                "expected_close_date",
                None if current is None else current.expected_close_date,
            ),
            "expected_close_date",
        )
    if not partial or "owner" in data:
        normalized["owner"] = clean_owner(
            actor,
            data.get("owner", None if current is None else current.owner_id),
        )
    if not partial or "notes" in data:
        notes = str(data.get("notes", "" if current is None else current.notes) or "")
        if len(notes) > 4000:
            raise ValidationError({"notes": "Use 4000 characters or fewer."})
        normalized["notes"] = notes.strip()
    stage = normalized.get("stage", current.stage if current else "")
    if not partial or "probability" in data or "stage" in normalized:
        supplied = data.get("probability") if "probability" in data else None
        if "probability" not in data and current is not None and "stage" not in data:
            supplied = current.probability
        elif (
            "probability" not in data and "stage" in normalized and current is not None
        ):
            if normalized["stage"] == current.stage:
                supplied = current.probability
        normalized["probability"] = _probability(stage, supplied)
    return normalized


def filter_deals(user, params):
    queryset = scoped(Deal.objects.select_related("owner", "lead"), user)
    query = str(params.get("q") or "").strip()
    if len(query) > 100:
        raise ValidationError({"q": "Use 100 characters or fewer."})
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query) | Q(lead__company_name__icontains=query)
        )
    if params.get("stage"):
        queryset = queryset.filter(
            stage=clean_known_key("DEAL_STAGE", params.get("stage"), "stage")
        )
    if params.get("deal_type"):
        queryset = queryset.filter(
            deal_type=clean_known_key("DEAL_TYPE", params.get("deal_type"), "deal_type")
        )
    if params.get("temperature"):
        queryset = queryset.filter(
            temperature=clean_known_key(
                "TEMPERATURE", params.get("temperature"), "temperature"
            )
        )
    if params.get("owner"):
        queryset = queryset.filter(owner=clean_owner(user, params.get("owner")))
    if params.get("lead"):
        queryset = queryset.filter(lead=_visible_lead(user, params.get("lead")))
    if params.get("close_after"):
        queryset = queryset.filter(
            expected_close_date__gte=clean_date(
                params.get("close_after"), "close_after"
            )
        )
    if params.get("close_before"):
        queryset = queryset.filter(
            expected_close_date__lte=clean_date(
                params.get("close_before"), "close_before"
            )
        )
    ordering = params.get("ordering") or "-created_at"
    if ordering not in DEAL_ORDERING:
        raise ValidationError({"ordering": "Sorting is limited to indexed fields."})
    return queryset.order_by(DEAL_ORDERING[ordering], "pk")


@transaction.atomic
def create_deal(*, actor, data, request_id=""):
    normalized = normalize_deal(actor, data)
    deal = Deal(
        created_by=actor,
        updated_by=actor,
        stage_entered_at=timezone.now(),
        version=1,
        **normalized,
    )
    deal.full_clean()
    deal.save()
    _record(actor, "deal.created", deal, None, request_id)
    return deal


@transaction.atomic
def update_deal(*, actor, deal_id, version, data, request_id=""):
    deal = get_scoped(Deal, actor, deal_id, for_update=True, related=("owner", "lead"))
    if require_version(version) != deal.version:
        raise VersionConflict
    normalized = normalize_deal(actor, data, current=deal)
    if not normalized:
        return deal
    before = deal_snapshot(deal)
    stage_changed = "stage" in normalized and normalized["stage"] != deal.stage
    for field, value in normalized.items():
        setattr(deal, field, value)
    if stage_changed:
        deal.stage_entered_at = timezone.now()
    deal.updated_by = actor
    deal.version += 1
    deal.full_clean()
    deal.save()
    _record(actor, "deal.updated", deal, before, request_id)
    return deal


@transaction.atomic
def delete_deal(*, actor, deal_id, version, delete_reason, request_id=""):
    deal = get_scoped(Deal, actor, deal_id, for_update=True, related=("owner", "lead"))
    if require_version(version) != deal.version:
        raise VersionConflict
    before = deal_snapshot(deal)
    deal.deleted_at = datetime.now(UTC)
    deal.deleted_by = actor
    deal.delete_reason = clean_delete_reason(delete_reason)
    deal.updated_by = actor
    deal.version += 1
    deal.save()
    _record(actor, "deal.deleted", deal, before, request_id)
    return deal


def deal_payload(deal: Deal) -> dict:
    return {
        "id": str(deal.pk),
        "external_id": deal.external_id,
        "title": deal.title,
        "lead": str(deal.lead_id),
        "lead_company": deal.lead.company_name,
        "deal_type": deal.deal_type,
        "amount": None if deal.amount is None else str(deal.amount),
        "currency": deal.currency,
        "temperature": deal.temperature,
        "expected_close_date": (
            None
            if deal.expected_close_date is None
            else deal.expected_close_date.isoformat()
        ),
        "owner": deal.owner_id,
        "owner_name": deal.owner.display_name,
        "stage": deal.stage,
        "probability": str(deal.probability),
        "notes": deal.notes,
        "version": deal.version,
        "created_at": deal.created_at.isoformat(),
        "updated_at": deal.updated_at.isoformat(),
    }
