"""Lead conversion. One transaction, and a second submit returns the first result."""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Account, Contact
from accounts.services import (
    CONVERTIBLE_ACCOUNT_TYPES,
    account_candidates,
    contact_differences,
    create_account,
    create_contact,
    mark_primary,
    normalize_name,
)
from audit.models import AuditEvent
from core.access import get_scoped
from core.exceptions import VersionConflict
from core.validation import clean_email, clean_external_id, require_version
from core.workflow import OPEN_DEAL_STAGES
from leads.models import Lead
from sales.models import Deal
from sales.services import create_deal, deal_snapshot

logger = logging.getLogger(__name__)


class ConversionChoiceRequired(ValidationError):
    """The caller must pick a candidate or confirm a new record."""

    def __init__(self, payload):
        self.payload = payload
        super().__init__({"conversion": payload["detail"]})


def contact_candidates(*, account, email, first_name, last_name, title):
    found = {}
    normalized_email = ""
    if email:
        normalized_email, _domain = clean_email(email)
    if normalized_email:
        for contact in Contact.objects.filter(
            account=account, email_normalized=normalized_email
        ):
            found[contact.pk] = _contact_candidate(contact, 100, "Same email")
    person = normalize_name(f"{first_name} {last_name}")
    role = normalize_name(title)
    if person:
        for contact in account.contacts.all():
            same_person = (
                normalize_name(f"{contact.first_name} {contact.last_name}") == person
            )
            same_role = normalize_name(contact.title) == role
            if same_person and same_role:
                current = found.get(contact.pk)
                if current is None:
                    found[contact.pk] = _contact_candidate(
                        contact, 80, "Same name and title"
                    )
                elif "Same name and title" not in current["reasons"]:
                    current["reasons"].append("Same name and title")
                    current["score"] = max(current["score"], 80)
    return sorted(found.values(), key=lambda item: (-item["score"], item["name"]))


def _contact_candidate(contact, score, reason):
    return {
        "id": str(contact.pk),
        "name": str(contact),
        "email": contact.email,
        "score": score,
        "reasons": [reason],
    }


def _truthy(value):
    return value in (True, "1", "true", "on", 1)


def exact_account_for_lead(lead):
    """Return an account with the same domain or the same name.

    A similar name is not a match. This does not create or change a record.
    """
    if lead.website_domain:
        match = (
            Account.objects.filter(website_domain=lead.website_domain)
            .order_by("created_at")
            .first()
        )
        if match is not None:
            return match
    normalized = normalize_name(lead.company_name)
    if not normalized:
        return None
    return (
        Account.objects.filter(name_normalized=normalized)
        .order_by("created_at")
        .first()
    )


@transaction.atomic
def convert_lead(*, actor, lead_id, version, data, request_id="", fail_at=""):
    lead = get_scoped(Lead, actor, lead_id, for_update=True)
    if lead.converted_at is not None:
        return {
            "lead_id": str(lead.pk),
            "account_id": str(lead.converted_account_id),
            "contact_id": str(lead.converted_contact_id),
            "idempotent": True,
        }
    if require_version(version) != lead.version:
        raise VersionConflict
    account = _account(actor, lead, data, request_id)
    if fail_at == "after_account":
        raise RuntimeError("injected conversion failure")
    contact = _contact(actor, lead, account, data, request_id)
    if fail_at == "after_contact":
        raise RuntimeError("injected conversion failure")
    _deals(actor, lead, account, contact, data, request_id)
    from activities.services import create_activity

    create_activity(
        actor=actor,
        data={
            "activity_type": "NOTE",
            "subject": "Lead converted",
            "body": "Converted to an account and contact.",
        },
        links=[
            {"kind": "lead", "id": lead.pk},
            {"kind": "account", "id": account.pk},
        ],
        request_id=request_id,
    )
    lead.converted_at = timezone.now()
    lead.converted_account = account
    lead.converted_contact = contact
    lead.updated_by = actor
    lead.version += 1
    lead.save(
        update_fields=(
            "converted_at",
            "converted_account",
            "converted_contact",
            "updated_by",
            "version",
            "updated_at",
        )
    )
    AuditEvent.objects.create(
        actor=actor,
        action="lead.converted",
        object_type="leads.lead",
        object_id=str(lead.pk),
        before_json=None,
        after_json={
            "account_id": str(account.pk),
            "contact_id": str(contact.pk),
            "version": lead.version,
        },
        request_id=request_id,
        source="web",
    )
    logger.info(
        "lead.converted",
        extra={"object_id": str(lead.pk), "outcome": "success"},
    )
    return {
        "lead_id": str(lead.pk),
        "account_id": str(account.pk),
        "contact_id": str(contact.pk),
        "idempotent": False,
    }


def _account(actor, lead, data, request_id):
    mode = str(data.get("account_mode") or "create")
    if mode == "existing":
        account = get_scoped(Account, actor, data.get("account_id"))
        _permitted_type(actor, account.account_type)
        return account
    if mode != "create":
        raise ValidationError({"account_mode": "Choose create or existing."})
    name = str(data.get("account_name") or lead.company_name).strip()
    domain = lead.website_domain
    candidates = account_candidates(name=name, domain=domain)
    if candidates and not _truthy(data.get("confirm_new")):
        raise ConversionChoiceRequired(
            {
                "detail": "Choose an existing account or confirm a new one.",
                "account_candidates": candidates,
            }
        )
    if candidates and not str(data.get("justification") or "").strip():
        raise ValidationError({"justification": "Explain why this is a new account."})
    account_type = str(data.get("account_type") or Account.Type.PROSPECT)
    _permitted_type(actor, account_type)
    account = create_account(
        actor=actor,
        data={
            "name": name,
            "account_type": account_type,
            "website_url": lead.website_url,
            "owner": lead.owner_id,
        },
        request_id=request_id,
    )
    account.converted_from_lead = lead
    account.save(update_fields=("converted_from_lead", "updated_at"))
    return account


def _permitted_type(actor, account_type):
    if account_type in CONVERTIBLE_ACCOUNT_TYPES:
        return
    if actor.is_company_admin:
        return
    raise PermissionDenied


def _contact(actor, lead, account, data, request_id):
    mode = str(data.get("contact_mode") or "create")
    incoming = {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "email": lead.email,
        "title": lead.title,
    }
    if mode == "existing":
        contact = get_scoped(Contact, actor, data.get("contact_id"))
        if contact.account_id != account.pk:
            raise ValidationError({"contact": "Choose a contact on this account."})
        differences = contact_differences(contact, incoming)
        choices = data.get("field_choices") or {}
        unresolved = [
            item
            for item in differences
            if choices.get(item["field"]) not in ("keep", "use_lead")
        ]
        if unresolved:
            raise ConversionChoiceRequired(
                {
                    "detail": "Choose whether to keep or replace each different field.",
                    "differences": unresolved,
                }
            )
        _apply_choices(contact, incoming, choices, actor)
        if _truthy(data.get("is_primary", True)):
            mark_primary(actor=actor, contact=contact, request_id=request_id)
        return contact
    if mode != "create":
        raise ValidationError({"contact_mode": "Choose create or existing."})
    candidates = contact_candidates(
        account=account,
        email=lead.email,
        first_name=lead.first_name,
        last_name=lead.last_name,
        title=lead.title,
    )
    if candidates and not _truthy(data.get("confirm_new_contact")):
        raise ConversionChoiceRequired(
            {
                "detail": "Choose an existing contact or confirm a new one.",
                "contact_candidates": candidates,
            }
        )
    contact = create_contact(
        actor=actor,
        data={
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "title": lead.title,
            "email": lead.email,
            "account": account.pk,
            "owner": lead.owner_id,
            "is_primary": data.get("is_primary", True),
        },
        request_id=request_id,
    )
    contact.converted_from_lead = lead
    contact.save(update_fields=("converted_from_lead", "updated_at"))
    return contact


def _apply_choices(contact, incoming, choices, actor):
    changed = []
    for field, choice in choices.items():
        if choice != "use_lead" or field not in incoming:
            continue
        if field == "email":
            email, _domain = clean_email(incoming["email"])
            contact.email = email
            contact.email_normalized = email
            changed.extend(("email", "email_normalized"))
        else:
            setattr(contact, field, str(incoming[field] or "")[:120])
            changed.append(field)
    if not changed:
        return
    contact.updated_by = actor
    contact.version += 1
    changed.extend(("updated_by", "version", "updated_at"))
    contact.save(update_fields=tuple(dict.fromkeys(changed)))


def _deals(actor, lead, account, contact, data, request_id):
    action = str(data.get("deal_action") or "reparent")
    if action not in {"reparent", "leave", "create"}:
        raise ValidationError({"deal_action": "Choose reparent, leave, or create."})
    if action == "reparent":
        open_deals = Deal.objects.select_for_update().filter(
            lead=lead, stage__in=OPEN_DEAL_STAGES
        )
        for deal in open_deals:
            before = deal_snapshot(deal)
            deal.converted_from_lead = lead
            deal.account = account
            deal.lead = None
            deal.primary_contact = contact
            deal.updated_by = actor
            deal.version += 1
            deal.save()
            AuditEvent.objects.create(
                actor=actor,
                action="deal.reparented",
                object_type="sales.deal",
                object_id=str(deal.pk),
                before_json=before,
                after_json=deal_snapshot(deal),
                request_id=request_id,
                source="web",
            )
    if action == "create":
        title = str(data.get("deal_title") or f"{lead.company_name} opportunity")
        create_deal(
            actor=actor,
            data={
                "title": title[:200],
                "account": account.pk,
                "deal_type": "CONSULTING_SERVICES",
                "currency": "USD",
                "confidence": "MEDIUM",
                "stage": "NEW",
                "owner": lead.owner_id,
            },
            request_id=request_id,
        )


def prepare_lead_for_closed_deal(*, actor, lead, closed_stage, request_id=""):
    """Add the lead's company and person when a deal is won or lost.

    The lead stage is left as it is. A similar company name is not reused.
    """
    locked = Lead.objects.select_for_update().get(pk=lead.pk)
    if locked.converted_at is not None:
        return locked.converted_account, locked.converted_contact
    account = exact_account_for_lead(locked)
    if account is None:
        account_type = (
            Account.Type.CUSTOMER
            if closed_stage == "CLOSED_WON"
            else Account.Type.PROSPECT
        )
        account = create_account(
            actor=actor,
            data={
                "name": locked.company_name,
                "account_type": account_type,
                "website_url": locked.website_url,
                "owner": locked.owner_id,
            },
            request_id=request_id,
        )
        account.converted_from_lead = locked
        account.save(update_fields=("converted_from_lead", "updated_at"))
    contact = _contact_for_closed_lead(actor, locked, account)
    locked.converted_at = timezone.now()
    locked.converted_account = account
    locked.converted_contact = contact
    locked.updated_by = actor
    locked.version += 1
    locked.save(
        update_fields=(
            "converted_at",
            "converted_account",
            "converted_contact",
            "updated_by",
            "version",
            "updated_at",
        )
    )
    _conversion_note(actor, locked, account)
    AuditEvent.objects.create(
        actor=actor,
        action="lead.converted",
        object_type="leads.lead",
        object_id=str(locked.pk),
        before_json=None,
        after_json={
            "account_id": str(account.pk),
            "contact_id": str(contact.pk),
            "version": locked.version,
            "stage": locked.stage,
        },
        request_id=request_id,
        source="web",
    )
    return account, contact


def _contact_for_closed_lead(actor, lead, account):
    email, _domain = clean_email(lead.email or "")
    if email:
        existing = Contact.objects.filter(
            account=account, email_normalized=email
        ).first()
        if existing is not None:
            return existing
    has_primary = Contact.objects.filter(account=account, is_primary=True).exists()
    contact = Contact(
        external_id=clean_external_id(None),
        first_name=lead.first_name[:80],
        last_name=lead.last_name[:80],
        title=(lead.title or "")[:120],
        email=email,
        email_normalized=email,
        account=account,
        owner=lead.owner,
        is_primary=False,
        converted_from_lead=lead,
        created_by=actor,
        updated_by=actor,
    )
    contact.full_clean()
    contact.save()
    if not has_primary:
        mark_primary(actor=actor, contact=contact)
    return contact


def _conversion_note(actor, lead, account):
    from django.contrib.contenttypes.models import ContentType

    from activities.models import Activity, ActivityLink

    activity = Activity(
        external_id=clean_external_id(None),
        activity_type=Activity.Type.NOTE,
        subject="Lead converted",
        body="Converted because a deal closed.",
        occurred_at=timezone.now(),
        owner=actor,
        created_by=actor,
        updated_by=actor,
        source="MANUAL",
    )
    activity.full_clean()
    activity.save()
    for record in (lead, account):
        ActivityLink.objects.create(
            activity=activity,
            content_type=ContentType.objects.get_for_model(record),
            object_id=record.pk,
        )
