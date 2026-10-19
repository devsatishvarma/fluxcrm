"""Deal list, change, and audit operations."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.http import Http404
from django.utils import timezone

from audit.models import AuditEvent
from core.access import get_scoped, scoped
from core.display import age_days
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

DEAL_RELATED = ("owner", "lead", "account", "converted_from_lead", "primary_contact")

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
    "confidence": "confidence",
    "-confidence": "-confidence",
    "owner": "owner__display_name",
    "-owner": "-owner__display_name",
    "age": "created_at",
    "-age": "-created_at",
}
CONFIDENCE_RANK = Case(
    When(confidence="HIGH", then=Value(0)),
    When(confidence="MEDIUM", then=Value(1)),
    When(confidence="LOW", then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)


def deal_snapshot(deal: Deal) -> dict:
    return {
        "external_id": deal.external_id,
        "title": deal.title,
        "lead_id": None if deal.lead_id is None else str(deal.lead_id),
        "account_id": None if deal.account_id is None else str(deal.account_id),
        "primary_contact_id": (
            None if deal.primary_contact_id is None else str(deal.primary_contact_id)
        ),
        "converted_from_lead_id": (
            None
            if deal.converted_from_lead_id is None
            else str(deal.converted_from_lead_id)
        ),
        "stage": deal.stage,
        "probability": str(deal.probability),
        "outcome": deal.outcome,
        "close_reason": deal.close_reason,
        "evaluation_started_on": (
            None
            if deal.evaluation_started_on is None
            else deal.evaluation_started_on.isoformat()
        ),
        "technical_stakeholder_name": deal.technical_stakeholder_name,
        "actual_close_date": (
            None
            if deal.actual_close_date is None
            else deal.actual_close_date.isoformat()
        ),
        "deal_type": deal.deal_type,
        "amount": None if deal.amount is None else str(deal.amount),
        "currency": deal.currency,
        "confidence": deal.confidence,
        "owner_id": deal.owner_id,
        "version": deal.version,
        "deleted": deal.deleted_at is not None,
    }


def _record(actor, action, deal, before, request_id, extra=None):
    after = deal_snapshot(deal)
    if extra:
        after.update(extra)
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type="sales.deal",
        object_id=str(deal.pk),
        before_json=before,
        after_json=after,
        request_id=request_id,
        source="web",
    )
    logger.info(action, extra={"object_id": str(deal.pk), "outcome": "success"})


def _visible_lead(actor, lead_id):
    if not lead_id:
        raise ValidationError({"lead": "A deal must belong to a lead."})
    try:
        return get_scoped(Lead, actor, lead_id)
    except PermissionDenied:
        raise
    except Http404 as exc:
        raise ValidationError({"lead": "Select an active lead."}) from exc


def _visible_account(actor, account_id):
    if not account_id:
        raise ValidationError({"account": "Select an account."})
    try:
        from accounts.models import Account

        return get_scoped(Account, actor, account_id)
    except PermissionDenied:
        raise
    except Http404 as exc:
        raise ValidationError({"account": "Select an active account."}) from exc


def _visible_contact(actor, contact_id, account):
    if not contact_id:
        raise ValidationError({"primary_contact": "Select a contact on this account."})
    try:
        from accounts.models import Contact

        contact = get_scoped(Contact, actor, contact_id)
    except PermissionDenied as exc:
        raise ValidationError(
            {"primary_contact": "Select a contact on this account."}
        ) from exc
    except Http404 as exc:
        raise ValidationError(
            {"primary_contact": "Select a contact on this account."}
        ) from exc
    if contact.account_id != account.pk:
        raise ValidationError({"primary_contact": "Select a contact on this account."})
    return contact


def _deal_contact(actor, data, normalized, current):
    """An account deal names one contact on that account. A lead deal does not."""
    if normalized.get("lead") is not None:
        if data.get("primary_contact"):
            raise ValidationError(
                {
                    "primary_contact": (
                        "Choose a contact when the deal is on an account."
                    )
                }
            )
        normalized["primary_contact"] = None
        return
    account = normalized.get("account")
    if account is None and current is not None and "lead" not in normalized:
        account = current.account
    if account is None:
        return
    if current is not None and "primary_contact" not in data:
        return
    normalized["primary_contact"] = _visible_contact(
        actor, data.get("primary_contact") or None, account
    )


def _deal_source(actor, data, current):
    partial = current is not None
    if partial and "lead" not in data and "account" not in data:
        return {}
    if current is None:
        lead_id = data.get("lead") or None
        account_id = data.get("account") or None
    else:
        lead_id = data["lead"] if "lead" in data else current.lead_id
        account_id = data["account"] if "account" in data else current.account_id
    if lead_id in ("", None):
        lead_id = None
    if account_id in ("", None):
        account_id = None
    if bool(lead_id) == bool(account_id):
        raise ValidationError(
            {
                "lead": "Choose a lead or an account, not both.",
                "account": "Choose a lead or an account, not both.",
            }
        )
    if current is not None:
        if lead_id and current.account_id:
            raise ValidationError({"lead": "This deal stays on its account."})
        if account_id and current.lead_id:
            raise ValidationError({"account": "This deal stays on its lead."})
        if (
            account_id
            and current.account_id
            and str(account_id) != str(current.account_id)
        ):
            raise ValidationError({"account": "This deal stays on its account."})
    if lead_id:
        return {"lead": _visible_lead(actor, lead_id), "account": None}
    return {"lead": None, "account": _visible_account(actor, account_id)}


def _same_probability(left, right):
    return Decimal(left).quantize(Decimal("0.01")) == Decimal(right).quantize(
        Decimal("0.01")
    )


def _probability(stage, value):
    if value in (None, ""):
        return Decimal(DEAL_STAGE_PROBABILITY[stage])
    amount = clean_money(value, "probability")
    if amount is None or amount > Decimal("100.00"):
        raise ValidationError({"probability": "Enter a probability from 0 to 100."})
    return amount


def confidence_for_probability(probability):
    """High at 80% or more, Medium from 40% up to 80%, Low under 40%."""
    amount = Decimal(probability)
    if amount >= Decimal("80"):
        return "HIGH"
    if amount >= Decimal("40"):
        return "MEDIUM"
    return "LOW"


def normalize_deal(actor, data, *, current=None):
    partial = current is not None
    normalized = {}
    normalized.update(_deal_source(actor, data, current))
    _deal_contact(actor, data, normalized, current)
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
    if not partial or "actual_close_date" in data:
        normalized["actual_close_date"] = clean_date(
            data.get(
                "actual_close_date",
                None if current is None else current.actual_close_date,
            ),
            "actual_close_date",
        )
    if not partial or "evaluation_started_on" in data:
        normalized["evaluation_started_on"] = clean_date(
            data.get(
                "evaluation_started_on",
                None if current is None else current.evaluation_started_on,
            ),
            "evaluation_started_on",
        )
    if not partial or "owner" in data:
        normalized["owner"] = clean_owner(
            actor,
            data.get("owner", None if current is None else current.owner_id),
            object_key="deal",
        )
    if not partial or "notes" in data:
        notes = str(data.get("notes", "" if current is None else current.notes) or "")
        if len(notes) > 4000:
            raise ValidationError({"notes": "Use 4000 characters or fewer."})
        normalized["notes"] = notes.strip()
    for field in (
        "bant_budget_status",
        "bant_authority_status",
        "bant_need_status",
        "bant_timeline_status",
    ):
        if partial and field not in data:
            continue
        raw = data.get(field)
        if raw in (None, ""):
            raw = "UNKNOWN" if current is None else getattr(current, field)
        normalized[field] = clean_required_key("BANT_STATUS", raw, field)
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
    probability = normalized.get(
        "probability", None if current is None else current.probability
    )
    if probability is not None:
        normalized["confidence"] = confidence_for_probability(probability)
    return normalized


def filter_deals(user, params):
    queryset = scoped(
        Deal.objects.select_related("owner", "lead", "account", "primary_contact"),
        user,
    )
    query = str(params.get("q") or "").strip()
    if len(query) > 100:
        raise ValidationError({"q": "Use 100 characters or fewer."})
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(lead__company_name__icontains=query)
            | Q(account__name__icontains=query)
        )
    if params.get("stage"):
        queryset = queryset.filter(
            stage=clean_known_key("DEAL_STAGE", params.get("stage"), "stage")
        )
    if params.get("deal_type"):
        queryset = queryset.filter(
            deal_type=clean_known_key("DEAL_TYPE", params.get("deal_type"), "deal_type")
        )
    if params.get("confidence"):
        queryset = queryset.filter(
            confidence=clean_known_key(
                "DEAL_CONFIDENCE", params.get("confidence"), "confidence"
            )
        )
    if params.get("owner"):
        queryset = queryset.filter(
            owner=clean_owner(user, params.get("owner"), object_key="deal")
        )
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
    from core.workflow import CLOSED_DEAL_STAGES

    closed_last = Case(
        When(stage__in=CLOSED_DEAL_STAGES, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    if ordering == "confidence":
        chosen_order = CONFIDENCE_RANK
    elif ordering == "-confidence":
        chosen_order = CONFIDENCE_RANK.desc()
    else:
        chosen_order = DEAL_ORDERING[ordering]
    if ordering in {"confidence", "-confidence"}:
        return queryset.order_by(chosen_order, "pk")
    return queryset.order_by(closed_last, chosen_order, "pk")


@transaction.atomic
def create_deal(*, actor, data, request_id=""):
    from core.policy import require_action
    from leads.models import Lead

    lead = None
    raw_lead = data.get("lead") if hasattr(data, "get") else None
    if raw_lead:
        lead = Lead.objects.filter(pk=raw_lead).first()
    require_action(actor, "deal", "C", lead=lead, object_id=raw_lead or "")
    requested_stage = str(data.get("stage") or "NEW").strip().upper()
    if requested_stage != "NEW":
        raise ValidationError(
            {"stage": "New deals must start at NEW; use a stage transition afterward."}
        )
    initial_data = data.copy()
    initial_data["stage"] = "NEW"
    normalized = normalize_deal(actor, initial_data)
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
    from core.policy import can_correct, require_action

    require_action(actor, "deal", "U", object_id=deal_id)
    deal = get_scoped(Deal, actor, deal_id, for_update=True, related=DEAL_RELATED)
    if require_version(version) != deal.version:
        raise VersionConflict
    normalized = normalize_deal(actor, data, current=deal)
    if not normalized:
        return deal
    before = deal_snapshot(deal)
    if "stage" in normalized and normalized["stage"] != deal.stage:
        raise ValidationError(
            {"stage": "Change stage from the board or the transition action."}
        )
    probability_changed = "probability" in normalized and not _same_probability(
        normalized["probability"], deal.probability
    )
    reason = str(data.get("probability_reason") or "").strip()
    if probability_changed and not can_correct(actor):
        raise PermissionDenied
    if probability_changed and not reason:
        raise ValidationError(
            {"probability_reason": ("Enter why the win probability changed.")}
        )
    for field, value in normalized.items():
        setattr(deal, field, value)
    deal.updated_by = actor
    deal.version += 1
    deal.full_clean()
    deal.save()
    if probability_changed:
        from core.models import StageHistory

        StageHistory.objects.create(
            object_type="deal",
            object_id=deal.pk,
            from_stage=deal.stage,
            to_stage=deal.stage,
            changed_by=actor,
            duration_seconds=0,
            probability_snapshot=deal.probability,
            probability_reason=reason[:500],
        )
    _record(
        actor,
        "deal.updated",
        deal,
        before,
        request_id,
        {"probability_reason": reason} if probability_changed else None,
    )
    return deal


@transaction.atomic
def delete_deal(*, actor, deal_id, version, delete_reason, request_id=""):
    from core.policy import require_action

    require_action(actor, "deal", "D", object_id=deal_id)
    deal = get_scoped(Deal, actor, deal_id, for_update=True, related=DEAL_RELATED)
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
        "lead": None if deal.lead_id is None else str(deal.lead_id),
        "lead_company": "" if deal.lead_id is None else deal.lead.company_name,
        "account": None if deal.account_id is None else str(deal.account_id),
        "account_name": "" if deal.account_id is None else deal.account.name,
        "primary_contact": (
            None if deal.primary_contact_id is None else str(deal.primary_contact_id)
        ),
        "primary_contact_name": (
            "" if deal.primary_contact_id is None else str(deal.primary_contact)
        ),
        "converted_from_lead": (
            None
            if deal.converted_from_lead_id is None
            else str(deal.converted_from_lead_id)
        ),
        "deal_type": deal.deal_type,
        "amount": None if deal.amount is None else str(deal.amount),
        "currency": deal.currency,
        "confidence": deal.confidence,
        "age_days": age_days(deal.created_at),
        "stage_age_days": age_days(deal.stage_entered_at),
        "expected_close_date": (
            None
            if deal.expected_close_date is None
            else deal.expected_close_date.isoformat()
        ),
        "actual_close_date": (
            None
            if deal.actual_close_date is None
            else deal.actual_close_date.isoformat()
        ),
        "evaluation_started_on": (
            None
            if deal.evaluation_started_on is None
            else deal.evaluation_started_on.isoformat()
        ),
        "technical_stakeholder_name": deal.technical_stakeholder_name,
        "owner": deal.owner_id,
        "owner_name": deal.owner.display_name,
        "stage": deal.stage,
        "probability": str(deal.probability),
        "bant_budget_status": deal.bant_budget_status,
        "bant_authority_status": deal.bant_authority_status,
        "bant_need_status": deal.bant_need_status,
        "bant_timeline_status": deal.bant_timeline_status,
        "close_reason": deal.close_reason,
        "outcome": deal.outcome,
        "notes": deal.notes,
        "version": deal.version,
        "created_at": deal.created_at.isoformat(),
        "updated_at": deal.updated_at.isoformat(),
    }


def deal_history(deal: Deal):
    from core.models import StageHistory

    return StageHistory.objects.filter(object_type="deal", object_id=deal.pk)


def owner_amount_totals(queryset):
    """Amount of the current deal list, grouped by owner."""
    rows = (
        queryset.order_by()
        .values("owner_id", "owner__display_name")
        .annotate(total=Sum("amount"))
        .order_by("owner__display_name")
    )
    return [
        {
            "name": row["owner__display_name"] or "—",
            "total": row["total"] or Decimal("0.00"),
        }
        for row in rows
    ]


def open_pipeline_total(user):
    from core.workflow import OPEN_DEAL_STAGES

    total = (
        filter_deals(user, {})
        .filter(stage__in=OPEN_DEAL_STAGES)
        .aggregate(total=Sum("amount"))["total"]
    )
    return total or Decimal("0.00")


@transaction.atomic
def transition_deal(
    *,
    actor,
    deal_id,
    version,
    to_stage,
    reason="",
    data=None,
    correction=False,
    request_id="",
):
    from django.core.exceptions import PermissionDenied

    from core.models import StageHistory
    from core.policy import can_correct, require_action
    from core.taxonomy import DEAL_STAGE_PROBABILITY
    from core.workflow import (
        DEAL_GRAPH,
        OPEN_DEAL_STAGES,
        deal_gate_gaps,
        stage_is_active,
    )

    require_action(actor, "deal", "U", object_id=deal_id)
    deal = get_scoped(Deal, actor, deal_id, for_update=True, related=DEAL_RELATED)
    if require_version(version) != deal.version:
        raise VersionConflict
    destination = str(to_stage or "").strip()
    note = str(reason or "").strip()
    incoming = data or {}
    if not stage_is_active("DEAL_STAGE", destination):
        raise ValidationError({"to_stage": "That stage is unknown or retired."})
    if correction:
        if not can_correct(actor):
            raise PermissionDenied
        if not note:
            raise ValidationError({"reason": "A correction requires a reason."})
    elif destination not in DEAL_GRAPH.get(deal.stage, ()):
        raise ValidationError({"to_stage": "That stage move is not allowed."})
    if incoming.get("amount") not in (None, ""):
        deal.amount = clean_money(incoming.get("amount"))
    if incoming.get("expected_close_date") not in (None, ""):
        deal.expected_close_date = clean_date(
            incoming.get("expected_close_date"), "expected_close_date"
        )
    if incoming.get("actual_close_date") not in (None, ""):
        deal.actual_close_date = clean_date(
            incoming.get("actual_close_date"), "actual_close_date"
        )
    if incoming.get("evaluation_started_on") not in (None, ""):
        deal.evaluation_started_on = clean_date(
            incoming.get("evaluation_started_on"), "evaluation_started_on"
        )
    if incoming.get("technical_stakeholder_name") not in (None, ""):
        deal.technical_stakeholder_name = str(
            incoming.get("technical_stakeholder_name")
        ).strip()[:120]
    for field in (
        "bant_budget_status",
        "bant_authority_status",
        "bant_need_status",
        "bant_timeline_status",
    ):
        if incoming.get(field):
            setattr(
                deal,
                field,
                clean_required_key("BANT_STATUS", incoming.get(field), field),
            )
    if destination in {"CLOSED_LOST", "CLOSED_HOLD"}:
        reason_list = (
            "CLOSED_LOST_REASON"
            if destination == "CLOSED_LOST"
            else "CLOSED_HOLD_REASON"
        )
        deal.close_reason = clean_required_key(
            reason_list,
            incoming.get("close_reason") or deal.close_reason,
            "close_reason",
        )
    probability = Decimal(DEAL_STAGE_PROBABILITY[destination])
    probability_reason = ""
    supplied = incoming.get("probability")
    if supplied not in (None, ""):
        override = clean_money(supplied, "probability")
        if override != probability:
            if not can_correct(actor):
                raise PermissionDenied
            if not str(incoming.get("probability_reason") or "").strip():
                raise ValidationError(
                    {"probability_reason": ("Enter why the win probability changed.")}
                )
            probability = override
            probability_reason = str(incoming["probability_reason"]).strip()
    if not correction or destination in {"CLOSED_WON", "CLOSED_LOST", "CLOSED_HOLD"}:
        gaps = deal_gate_gaps(deal, destination, note)
        if gaps:
            raise ValidationError({"detail": " ".join(gaps), "missing": gaps})
    if destination == "CLOSED_WON":
        deal.outcome = "WON"
    elif destination == "CLOSED_LOST":
        deal.outcome = "LOST"
        deal.actual_close_date = None
    elif destination == "CLOSED_HOLD":
        deal.outcome = "HOLD"
        deal.actual_close_date = None
    elif destination in OPEN_DEAL_STAGES:
        deal.outcome = ""
        deal.close_reason = ""
        deal.actual_close_date = None
    before = deal_snapshot(deal)
    now = timezone.now()
    duration = max(int((now - deal.stage_entered_at).total_seconds()), 0)
    StageHistory.objects.create(
        object_type="deal",
        object_id=deal.pk,
        from_stage=deal.stage,
        to_stage=destination,
        changed_by=actor,
        duration_seconds=duration,
        probability_snapshot=probability,
        probability_reason=probability_reason[:500],
        reason=note[:500],
        correction=correction,
    )
    deal.stage = destination
    deal.probability = probability
    deal.confidence = confidence_for_probability(probability)
    deal.stage_entered_at = now
    deal.updated_by = actor
    if destination in {"CLOSED_WON", "CLOSED_LOST"} and deal.lead_id:
        from accounts.conversion import prepare_lead_for_closed_deal

        account, contact = prepare_lead_for_closed_deal(
            actor=actor,
            lead=deal.lead,
            closed_stage=destination,
            request_id=request_id,
        )
        deal.converted_from_lead = deal.lead
        deal.account = account
        deal.primary_contact = contact
        deal.lead = None
    deal.version += 1
    deal.full_clean()
    deal.save()
    _record(
        actor,
        "deal.corrected" if correction else "deal.stage_changed",
        deal,
        before,
        request_id,
    )
    return deal
