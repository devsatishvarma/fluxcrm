"""Lead list, change, and audit operations."""

import logging
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from audit.models import AuditEvent
from core.access import get_scoped, scoped
from core.display import age_days
from core.exceptions import VersionConflict
from core.validation import (
    clean_address,
    clean_date,
    clean_datetime,
    clean_delete_reason,
    clean_email,
    clean_external_id,
    clean_known_key,
    clean_money,
    clean_optional_key,
    clean_owner,
    clean_phone,
    clean_required_key,
    clean_website,
    require_version,
)
from leads.models import Lead

logger = logging.getLogger(__name__)

LEAD_ORDERING = {
    "created_at": "created_at",
    "-created_at": "-created_at",
    "updated_at": "updated_at",
    "-updated_at": "-updated_at",
    "company_name": "company_name",
    "-company_name": "-company_name",
    "stage": "stage",
    "-stage": "-stage",
    "rating": "rating",
    "-rating": "-rating",
    "follow_up": "next_follow_up_at",
    "-follow_up": "-next_follow_up_at",
    "owner": "owner__display_name",
    "-owner": "-owner__display_name",
    "age": "created_at",
    "-age": "-created_at",
}
UPDATABLE = (
    "first_name",
    "last_name",
    "title",
    "email",
    "work_phone",
    "mobile_phone",
    "address",
    "company_name",
    "website_url",
    "industry",
    "products_services",
    "company_size_band",
    "employee_count",
    "annual_revenue",
    "source",
    "stage",
    "contact_substatus",
    "owner",
    "nurture_reason",
    "disqualification_reason",
    "next_follow_up_at",
    "notes",
)


def lead_snapshot(lead: Lead) -> dict:
    return {
        "external_id": lead.external_id,
        "stage": lead.stage,
        "source": lead.source,
        "rating": lead.rating,
        "owner_id": lead.owner_id,
        "version": lead.version,
        "company_name": lead.company_name,
        "deleted": lead.deleted_at is not None,
    }


def _record(actor, action, lead, before, request_id):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type="leads.lead",
        object_id=str(lead.pk),
        before_json=before,
        after_json=lead_snapshot(lead),
        request_id=request_id,
        source="web",
    )
    logger.info(action, extra={"object_id": str(lead.pk), "outcome": "success"})


def _value(data, key, current, default=""):
    if key in data:
        return data[key]
    return current if current is not None else default


def normalize_lead(actor, data, *, current=None):
    """Validate a full lead or a partial change set."""
    partial = current is not None
    normalized = {}
    if not partial or "external_id" in data:
        normalized["external_id"] = clean_external_id(
            data.get("external_id"),
            current=None if current is None else current.external_id,
        )
    text_fields = {
        "first_name": 80,
        "last_name": 80,
        "title": 120,
        "company_name": 200,
        "products_services": 255,
        "notes": 4000,
    }
    for field, limit in text_fields.items():
        if partial and field not in data:
            continue
        value = str(_value(data, field, getattr(current, field, "")) or "").strip()
        if field in {"first_name", "last_name", "company_name"} and not value:
            raise ValidationError({field: "This field is required."})
        if len(value) > limit:
            raise ValidationError({field: f"Use {limit} characters or fewer."})
        normalized[field] = value
    for field in ("work_phone", "mobile_phone"):
        if partial and field not in data:
            continue
        normalized[field] = clean_phone(
            _value(data, field, getattr(current, field, "")),
            field=field,
        )
    if not partial or "email" in data:
        email, domain = clean_email(
            _value(data, "email", getattr(current, "email", ""))
        )
        if not email:
            raise ValidationError({"email": "Enter an email address."})
        normalized["email"] = email
        normalized["email_normalized"] = email
        normalized["email_domain"] = domain
    if not partial or "website_url" in data:
        website, host = clean_website(
            _value(data, "website_url", getattr(current, "website_url", ""))
        )
        normalized["website_url"] = website
        normalized["website_domain"] = host
    if not partial or "source" in data:
        normalized["source"] = clean_required_key(
            "LEAD_SOURCE",
            _value(data, "source", getattr(current, "source", "")),
            "source",
        )
    if not partial or "rating" in data:
        raw_rating = _value(data, "rating", getattr(current, "rating", "WARM"))
        if raw_rating in (None, ""):
            raw_rating = "WARM"
        normalized["rating"] = clean_required_key(
            "LEAD_RATING",
            raw_rating,
            "rating",
        )
    if not partial or "stage" in data:
        normalized["stage"] = clean_required_key(
            "LEAD_STAGE",
            _value(data, "stage", getattr(current, "stage", "")),
            "stage",
        )
    if not partial or "industry" in data:
        normalized["industry"] = clean_optional_key(
            "INDUSTRY",
            _value(data, "industry", getattr(current, "industry", "")),
            "industry",
        )
    if not partial or "company_size_band" in data:
        normalized["company_size_band"] = clean_optional_key(
            "COMPANY_SIZE",
            _value(
                data, "company_size_band", getattr(current, "company_size_band", "")
            ),
            "company_size_band",
        )
    if not partial or "current_tools" in data:
        normalized["current_tools"] = clean_optional_key(
            "CURRENT_TOOLS",
            _value(data, "current_tools", getattr(current, "current_tools", "")),
            "current_tools",
        )
    if not partial or "budget_range" in data:
        normalized["budget_range"] = clean_optional_key(
            "BUDGET_RANGE",
            _value(data, "budget_range", getattr(current, "budget_range", "")),
            "budget_range",
        )
    if not partial or "buying_timeline" in data:
        normalized["buying_timeline"] = clean_optional_key(
            "BUYING_TIMELINE",
            _value(data, "buying_timeline", getattr(current, "buying_timeline", "")),
            "buying_timeline",
        )
    if not partial or "contact_substatus" in data:
        normalized["contact_substatus"] = clean_optional_key(
            "CONTACT_SUBSTATUS",
            _value(
                data, "contact_substatus", getattr(current, "contact_substatus", "")
            ),
            "contact_substatus",
        )
    if not partial or "nurture_reason" in data:
        normalized["nurture_reason"] = clean_optional_key(
            "NURTURE_REASON",
            _value(data, "nurture_reason", getattr(current, "nurture_reason", "")),
            "nurture_reason",
        )
    if not partial or "disqualification_reason" in data:
        normalized["disqualification_reason"] = clean_optional_key(
            "DISQUALIFICATION_REASON",
            _value(
                data,
                "disqualification_reason",
                getattr(current, "disqualification_reason", ""),
            ),
            "disqualification_reason",
        )
    if not partial or "owner" in data:
        normalized["owner"] = clean_owner(
            actor,
            data.get("owner", None if current is None else current.owner_id),
            object_key="lead",
        )
    if not partial or "employee_count" in data:
        raw_count = _value(
            data, "employee_count", getattr(current, "employee_count", None), None
        )
        if raw_count in (None, ""):
            normalized["employee_count"] = None
        else:
            try:
                count = int(raw_count)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    {"employee_count": "Enter a whole number."}
                ) from exc
            if count < 0:
                raise ValidationError(
                    {"employee_count": "Enter zero or a positive number."}
                )
            normalized["employee_count"] = count
    if not partial or "annual_revenue" in data:
        normalized["annual_revenue"] = clean_money(
            _value(
                data,
                "annual_revenue",
                getattr(current, "annual_revenue", None),
                None,
            ),
            "annual_revenue",
        )
    if not partial or "next_follow_up_at" in data:
        normalized["next_follow_up_at"] = clean_datetime(
            _value(
                data,
                "next_follow_up_at",
                getattr(current, "next_follow_up_at", None),
                None,
            ),
            "next_follow_up_at",
        )
    if not partial or "demo_scheduled_on" in data:
        normalized["demo_scheduled_on"] = clean_date(
            _value(
                data,
                "demo_scheduled_on",
                getattr(current, "demo_scheduled_on", None),
                None,
            ),
            "demo_scheduled_on",
        )
    if not partial or "technical_contact_name" in data:
        normalized["technical_contact_name"] = str(
            _value(
                data,
                "technical_contact_name",
                getattr(current, "technical_contact_name", ""),
            )
            or ""
        ).strip()[:120]
    if not partial or "address" in data:
        address = _value(data, "address", getattr(current, "address", {}), {})
        normalized["address"] = clean_address(address)
    stage = normalized.get("stage", current.stage if current else "")
    nurture = normalized.get(
        "nurture_reason", current.nurture_reason if current else ""
    )
    follow_up = normalized.get(
        "next_follow_up_at",
        current.next_follow_up_at if current else None,
    )
    disqualification = normalized.get(
        "disqualification_reason",
        current.disqualification_reason if current else "",
    )
    if stage == "NURTURING" and (not nurture or follow_up is None):
        raise ValidationError(
            {
                "nurture_reason": "Nurturing requires a reason and a next follow-up.",
                "next_follow_up_at": (
                    "Nurturing requires a reason and a next follow-up."
                ),
            }
        )
    if stage == "UNQUALIFIED" and not disqualification:
        raise ValidationError(
            {"disqualification_reason": "Unqualified leads require a reason."}
        )
    demo_on = normalized.get(
        "demo_scheduled_on",
        current.demo_scheduled_on if current else None,
    )
    technical_contact = normalized.get(
        "technical_contact_name",
        current.technical_contact_name if current else "",
    )
    if stage == "DEMO_POC" and (demo_on is None or not technical_contact):
        raise ValidationError(
            {
                "demo_scheduled_on": ("Demo needs a date and a technical contact."),
                "technical_contact_name": (
                    "Demo needs a date and a technical contact."
                ),
            }
        )
    return normalized


def filter_leads(user, params):
    queryset = scoped(Lead.objects.all(), user)
    if str(params.get("converted") or "") != "1":
        queryset = queryset.filter(converted_at__isnull=True)
    query = str(params.get("q") or "").strip()
    if len(query) > 100:
        raise ValidationError({"q": "Use 100 characters or fewer."})
    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(company_name__icontains=query)
            | Q(email_normalized__icontains=query)
        )
    if params.get("source"):
        queryset = queryset.filter(
            source=clean_known_key("LEAD_SOURCE", params.get("source"), "source")
        )
    if params.get("stage"):
        queryset = queryset.filter(
            stage=clean_known_key("LEAD_STAGE", params.get("stage"), "stage")
        )
    if params.get("rating"):
        queryset = queryset.filter(
            rating=clean_known_key("LEAD_RATING", params.get("rating"), "rating")
        )
    if params.get("owner"):
        queryset = queryset.filter(
            owner=clean_owner(user, params.get("owner"), object_key="lead")
        )
    if params.get("created_after"):
        queryset = queryset.filter(
            created_at__date__gte=clean_date(
                params.get("created_after"), "created_after"
            )
        )
    if params.get("created_before"):
        queryset = queryset.filter(
            created_at__date__lte=clean_date(
                params.get("created_before"), "created_before"
            )
        )
    ordering = params.get("ordering") or "-created_at"
    if ordering not in LEAD_ORDERING:
        raise ValidationError({"ordering": "Sorting is limited to indexed fields."})
    return queryset.order_by(LEAD_ORDERING[ordering], "pk")


def page_leads(queryset, page, page_size, *, strict=False):
    """Count and limit by primary key, then load that page with its owner.

    Selecting every column of a large ordered set makes MySQL sort the full
    rows. The id query stays on the open-list index.
    """
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
    from django.http import Http404

    identifiers = Paginator(
        queryset.select_related(None).values_list("pk", flat=True),
        page_size,
    )
    if strict:
        try:
            current = identifiers.page(page)
        except (EmptyPage, PageNotAnInteger) as exc:
            raise Http404("That page is outside the lead list.") from exc
    else:
        current = identifiers.get_page(page)
    ids = list(current.object_list)
    rows = {
        lead.pk: lead
        for lead in Lead.objects.select_related("owner").filter(pk__in=ids)
    }
    current.object_list = [rows[pk] for pk in ids if pk in rows]
    return current


@transaction.atomic
def create_lead(*, actor, data, request_id=""):
    from core.policy import require_action

    require_action(actor, "lead", "C")
    requested_stage = str(data.get("stage") or "NEW").strip().upper()
    if requested_stage != "NEW":
        raise ValidationError(
            {"stage": "New leads must start at NEW; use a stage transition afterward."}
        )
    initial_data = data.copy()
    initial_data["stage"] = "NEW"
    normalized = normalize_lead(actor, initial_data)
    now = timezone.now()
    lead = Lead(
        created_by=actor,
        updated_by=actor,
        stage_entered_at=now,
        version=1,
        **normalized,
    )
    lead.full_clean()
    lead.save()
    _record(actor, "lead.created", lead, None, request_id)
    return lead


@transaction.atomic
def update_lead(*, actor, lead_id, version, data, request_id=""):
    from core.policy import require_action

    require_action(actor, "lead", "U", object_id=lead_id)
    lead = get_scoped(Lead, actor, lead_id, for_update=True)
    if require_version(version) != lead.version:
        raise VersionConflict
    normalized = normalize_lead(actor, data, current=lead)
    if not normalized:
        return lead
    before = lead_snapshot(lead)
    if "stage" in normalized and normalized["stage"] != lead.stage:
        raise ValidationError(
            {"stage": "Change stage from the board or the transition action."}
        )
    for field, value in normalized.items():
        setattr(lead, field, value)
    lead.updated_by = actor
    lead.version += 1
    lead.full_clean()
    lead.save()
    _record(actor, "lead.updated", lead, before, request_id)
    return lead


@transaction.atomic
def delete_lead(*, actor, lead_id, version, delete_reason, request_id=""):
    from core.policy import require_action
    from sales.models import Deal

    require_action(actor, "lead", "D", object_id=lead_id)
    lead = get_scoped(Lead, actor, lead_id, for_update=True)
    if require_version(version) != lead.version:
        raise VersionConflict
    if Deal.objects.filter(lead=lead).exists():
        raise ValidationError(
            {"detail": "Delete this lead's deals before deleting the lead."}
        )
    before = lead_snapshot(lead)
    lead.deleted_at = datetime.now(UTC)
    lead.deleted_by = actor
    lead.delete_reason = clean_delete_reason(delete_reason)
    lead.updated_by = actor
    lead.version += 1
    lead.save()
    _record(actor, "lead.deleted", lead, before, request_id)
    return lead


@transaction.atomic
def restore_lead(*, actor, lead_id, version, request_id=""):
    from core.policy import require_action

    require_action(actor, "lead", "A", object_id=lead_id)
    try:
        lead = Lead.all_objects.select_for_update().get(pk=lead_id)
    except Lead.DoesNotExist as exc:
        from django.http import Http404

        raise Http404 from exc
    if lead.deleted_at is None:
        raise ValidationError({"detail": "This lead is not deleted."})
    if require_version(version) != lead.version:
        raise VersionConflict
    before = lead_snapshot(lead)
    lead.deleted_at = None
    lead.deleted_by = None
    lead.delete_reason = ""
    lead.updated_by = actor
    lead.version += 1
    lead.save()
    _record(actor, "lead.restored", lead, before, request_id)
    return lead


def lead_payload(lead: Lead) -> dict:
    return {
        "id": str(lead.pk),
        "external_id": lead.external_id,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "title": lead.title,
        "email": lead.email,
        "address": lead.address or {},
        "company_name": lead.company_name,
        "website_url": lead.website_url,
        "industry": lead.industry,
        "company_size_band": lead.company_size_band,
        "current_tools": lead.current_tools,
        "budget_range": lead.budget_range,
        "buying_timeline": lead.buying_timeline,
        "employee_count": lead.employee_count,
        "annual_revenue": (
            None if lead.annual_revenue is None else str(lead.annual_revenue)
        ),
        "source": lead.source,
        "rating": lead.rating,
        "age_days": age_days(lead.created_at),
        "stage_age_days": age_days(lead.stage_entered_at),
        "stage": lead.stage,
        "contact_substatus": lead.contact_substatus,
        "owner": lead.owner_id,
        "owner_name": lead.owner.display_name,
        "nurture_reason": lead.nurture_reason,
        "disqualification_reason": lead.disqualification_reason,
        "next_follow_up_at": (
            None
            if lead.next_follow_up_at is None
            else lead.next_follow_up_at.isoformat()
        ),
        "demo_scheduled_on": (
            None
            if lead.demo_scheduled_on is None
            else lead.demo_scheduled_on.isoformat()
        ),
        "technical_contact_name": lead.technical_contact_name,
        "notes": lead.notes,
        "converted_at": (
            None if lead.converted_at is None else lead.converted_at.isoformat()
        ),
        "converted_account": (
            None
            if lead.converted_account_id is None
            else str(lead.converted_account_id)
        ),
        "converted_contact": (
            None
            if lead.converted_contact_id is None
            else str(lead.converted_contact_id)
        ),
        "version": lead.version,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
    }


def lead_history(lead: Lead):
    from core.models import StageHistory

    return StageHistory.objects.filter(object_type="lead", object_id=lead.pk)


@transaction.atomic
def transition_lead(
    *,
    actor,
    lead_id,
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
    from core.workflow import LEAD_GRAPH, lead_gate_gaps, stage_is_active

    require_action(actor, "lead", "U", object_id=lead_id)
    lead = get_scoped(Lead, actor, lead_id, for_update=True)
    if require_version(version) != lead.version:
        raise VersionConflict
    destination = str(to_stage or "").strip()
    note = str(reason or "").strip()
    incoming = data or {}
    if not stage_is_active("LEAD_STAGE", destination):
        raise ValidationError({"to_stage": "That stage is unknown or retired."})
    if correction:
        if not can_correct(actor):
            raise PermissionDenied
        if not note:
            raise ValidationError({"reason": "A correction requires a reason."})
    elif destination not in LEAD_GRAPH.get(lead.stage, ()):
        raise ValidationError({"to_stage": "That stage move is not allowed."})
    elif lead.stage == "UNQUALIFIED" and not actor.is_company_admin:
        raise PermissionDenied
    for field, list_key in (
        ("contact_substatus", "CONTACT_SUBSTATUS"),
        ("nurture_reason", "NURTURE_REASON"),
        ("disqualification_reason", "DISQUALIFICATION_REASON"),
        ("company_size_band", "COMPANY_SIZE"),
        ("current_tools", "CURRENT_TOOLS"),
        ("budget_range", "BUDGET_RANGE"),
        ("buying_timeline", "BUYING_TIMELINE"),
    ):
        if incoming.get(field):
            setattr(lead, field, clean_optional_key(list_key, incoming[field], field))
    if "demo_scheduled_on" in incoming:
        lead.demo_scheduled_on = clean_date(
            incoming.get("demo_scheduled_on"), "demo_scheduled_on"
        )
    if incoming.get("technical_contact_name"):
        lead.technical_contact_name = str(
            incoming.get("technical_contact_name")
        ).strip()[:120]
    if "next_follow_up_at" in incoming:
        lead.next_follow_up_at = clean_datetime(
            incoming.get("next_follow_up_at"), "next_follow_up_at"
        )
    if incoming.get("notes"):
        lead.notes = str(incoming.get("notes")).strip()
    if not correction:
        gaps = lead_gate_gaps(lead, destination, note)
        if gaps:
            raise ValidationError({"detail": " ".join(gaps), "missing": gaps})
    before = lead_snapshot(lead)
    now = timezone.now()
    duration = max(int((now - lead.stage_entered_at).total_seconds()), 0)
    StageHistory.objects.create(
        object_type="lead",
        object_id=lead.pk,
        from_stage=lead.stage,
        to_stage=destination,
        changed_by=actor,
        duration_seconds=duration,
        reason=note[:500],
        correction=correction,
    )
    lead.stage = destination
    lead.stage_entered_at = now
    lead.updated_by = actor
    lead.version += 1
    lead.full_clean()
    lead.save()
    _record(
        actor,
        "lead.corrected" if correction else "lead.stage_changed",
        lead,
        before,
        request_id,
    )
    return lead


@transaction.atomic
def bulk_assign_leads(*, actor, lead_ids, owner, request_id=""):
    """Assign many visible leads to one owner inside the actor's scope."""
    from core.policy import require_action

    require_action(actor, "lead", "U")
    if not lead_ids:
        raise ValidationError({"lead": "Select at least one lead."})
    if len(lead_ids) > 50:
        raise ValidationError({"lead": "Assign up to 50 leads at a time."})
    target = clean_owner(actor, owner, object_key="lead")
    updated = []
    for lead_id in lead_ids:
        lead = get_scoped(Lead, actor, lead_id, for_update=True)
        if lead.owner_id == target.pk:
            updated.append(lead)
            continue
        before = lead_snapshot(lead)
        lead.owner = target
        lead.updated_by = actor
        lead.version += 1
        lead.save()
        _record(actor, "lead.updated", lead, before, request_id)
        updated.append(lead)
    return updated
