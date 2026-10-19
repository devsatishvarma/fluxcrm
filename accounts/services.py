"""Account and contact rules shared by the pages and the API."""

import logging
import re
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from accounts.models import Account, Contact
from audit.models import AuditEvent
from core.access import get_scoped, scoped
from core.exceptions import VersionConflict
from core.policy import require_action
from core.validation import (
    address_from_mapping,
    clean_delete_reason,
    clean_email,
    clean_external_id,
    clean_optional_key,
    clean_owner,
    clean_phone,
    clean_website,
    require_version,
)

logger = logging.getLogger(__name__)
CONVERTIBLE_ACCOUNT_TYPES = {Account.Type.CUSTOMER, Account.Type.PROSPECT}


def contacts_for_user(user):
    """Contacts this person can read, plus contacts on accounts they can open."""
    queryset = Contact.objects.select_related("account", "owner")
    visible_accounts = scoped(Account.objects.all(), user)
    return queryset.filter(
        Q(pk__in=scoped(queryset, user).values("pk")) | Q(account__in=visible_accounts)
    ).distinct()


def normalize_name(value):
    compact = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    return " ".join(compact.split())


def account_candidates(*, name, domain=""):
    """Explain possible matches. This never merges or overwrites a record."""
    found = {}
    normalized = normalize_name(name)
    if domain:
        for account in Account.objects.filter(website_domain=domain):
            found[account.pk] = _candidate(account, 100, "Same website domain")
    if normalized:
        for account in Account.objects.filter(name_normalized=normalized):
            _merge_candidate(found, account, 90, "Same account name")
        token = normalized.split()[0]
        if len(token) >= 4:
            for account in Account.objects.filter(name_normalized__icontains=token):
                if account.name_normalized == normalized:
                    continue
                _merge_candidate(found, account, 60, "Similar account name")
    return sorted(found.values(), key=lambda item: (-item["score"], item["name"]))


def _candidate(account, score, reason):
    return {
        "id": str(account.pk),
        "name": account.name,
        "account_type": account.account_type,
        "score": score,
        "reasons": [reason],
    }


def _merge_candidate(found, account, score, reason):
    current = found.get(account.pk)
    if current is None:
        found[account.pk] = _candidate(account, score, reason)
        return
    if reason not in current["reasons"]:
        current["reasons"].append(reason)
    current["score"] = max(current["score"], score)


def _ancestors(account):
    seen = set()
    current = account
    while current is not None:
        if current.pk in seen:
            raise ValidationError({"parent": "Account hierarchy cannot cycle."})
        seen.add(current.pk)
        current = current.parent
    return seen


def assert_account_parent(account, parent):
    if parent is None:
        return
    if account is not None and parent.pk == account.pk:
        raise ValidationError({"parent": "Account hierarchy cannot cycle."})
    ancestors = _ancestors(parent)
    if account is not None and account.pk in ancestors:
        raise ValidationError({"parent": "Account hierarchy cannot cycle."})


def assert_reports_to(contact, manager, *, allow_cross_account=False):
    if manager is None:
        return
    if contact is not None and manager.pk == contact.pk:
        raise ValidationError({"reports_to": "Reporting line cannot cycle."})
    if (
        contact is not None
        and manager.account_id != contact.account_id
        and not allow_cross_account
    ):
        raise ValidationError({"reports_to": "A contact reports inside one account."})
    seen = set()
    current = manager
    while current is not None:
        if current.pk in seen or (contact is not None and current.pk == contact.pk):
            raise ValidationError({"reports_to": "Reporting line cannot cycle."})
        seen.add(current.pk)
        current = current.reports_to


def _email(value):
    email, _domain = clean_email(value or "")
    if not email:
        raise ValidationError({"email": "Enter an email address."})
    return email


def _phone(value, field="phone"):
    return clean_phone(value, field=field)


def _notes(value):
    notes = str(value or "").strip()
    if len(notes) > 4000:
        raise ValidationError({"notes": "Use 4000 characters or fewer."})
    return notes


def _checked(value):
    return value in (True, "1", "true", "on", 1)


def account_snapshot(account):
    return {
        "name": account.name,
        "account_type": account.account_type,
        "parent_id": None if account.parent_id is None else str(account.parent_id),
        "industry": account.industry,
        "website_url": account.website_url,
        "phone": account.phone,
        "address": account.address or {},
        "owner_id": account.owner_id,
        "status": account.status,
        "version": account.version,
    }


def contact_snapshot(contact):
    return {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "title": contact.title,
        "email": contact.email,
        "work_phone": contact.work_phone,
        "mobile_phone": contact.mobile_phone,
        "address": contact.address or {},
        "account_id": str(contact.account_id),
        "is_primary": contact.is_primary,
        "reports_to_id": (
            None if contact.reports_to_id is None else str(contact.reports_to_id)
        ),
        "owner_id": contact.owner_id,
        "version": contact.version,
    }


def _audit(actor, action, instance, request_id, before=None, after=None):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        before_json=before,
        after_json=after
        or {"external_id": instance.external_id, "version": instance.version},
        request_id=request_id,
        source="web",
    )
    logger.info(action, extra={"object_id": str(instance.pk), "outcome": "success"})


@transaction.atomic
def create_account(*, actor, data, request_id=""):
    require_action(actor, "account", "C")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError({"name": "This field is required."})
    account_type = str(data.get("account_type") or "").strip()
    if account_type not in Account.Type.values:
        raise ValidationError({"account_type": "Choose an account type."})
    parent = None
    if data.get("parent"):
        parent = get_scoped(Account, actor, data.get("parent"))
        assert_account_parent(None, parent)
    website, domain = clean_website(data.get("website_url") or "")
    industry = clean_optional_key("INDUSTRY", data.get("industry") or "", "industry")
    status = str(data.get("status") or Account.Status.ACTIVE).strip()
    if status not in Account.Status.values:
        raise ValidationError({"status": "Choose a status."})
    notes = _notes(data.get("notes"))
    account = Account(
        external_id=clean_external_id(data.get("external_id")),
        name=name[:200],
        name_normalized=normalize_name(name)[:200],
        account_type=account_type,
        parent=parent,
        website_url=website,
        website_domain=domain,
        industry=industry,
        phone=_phone(data.get("phone")),
        address=address_from_mapping(data),
        owner=clean_owner(actor, data.get("owner"), object_key="account"),
        status=status,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )
    account.full_clean()
    account.save()
    _audit(actor, "account.created", account, request_id)
    return account


@transaction.atomic
def create_contact(*, actor, data, request_id=""):
    require_action(actor, "contact", "C")
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()
    if not first_name or not last_name:
        raise ValidationError(
            {
                "first_name": "This field is required.",
                "last_name": "This field is required.",
            }
        )
    account = get_scoped(Account, actor, data.get("account"))
    reports_to = None
    if data.get("reports_to"):
        reports_to = get_scoped(Contact, actor, data.get("reports_to"))
        if reports_to.account_id != account.pk and not actor.is_company_admin:
            raise ValidationError(
                {"reports_to": "A contact reports inside one account."}
            )
        assert_reports_to(
            None,
            reports_to,
            allow_cross_account=actor.is_company_admin,
        )
    email = _email(data.get("email"))
    contact = Contact(
        external_id=clean_external_id(data.get("external_id")),
        first_name=first_name[:80],
        last_name=last_name[:80],
        title=str(data.get("title") or "").strip()[:120],
        email=email,
        email_normalized=email,
        work_phone=_phone(data.get("work_phone"), "work_phone"),
        mobile_phone=_phone(data.get("mobile_phone"), "mobile_phone"),
        address=address_from_mapping(data),
        account=account,
        reports_to=reports_to,
        owner=clean_owner(
            actor, data.get("owner") or account.owner_id, object_key="contact"
        ),
        is_primary=False,
        notes=_notes(data.get("notes")),
        created_by=actor,
        updated_by=actor,
    )
    contact.full_clean()
    contact.save()
    if data.get("is_primary") in (True, "1", "true", 1):
        mark_primary(actor=actor, contact=contact, request_id=request_id)
    _audit(actor, "contact.created", contact, request_id)
    return contact


@transaction.atomic
def mark_primary(*, actor, contact, request_id=""):
    """Keep one primary contact by locking the account row first."""
    require_action(actor, "contact", "U", object_id=contact.pk)
    Account.objects.select_for_update().get(pk=contact.account_id)
    Contact.objects.filter(account_id=contact.account_id, is_primary=True).exclude(
        pk=contact.pk
    ).update(is_primary=False)
    contact.is_primary = True
    contact.updated_by = actor
    contact.version += 1
    contact.save(update_fields=("is_primary", "updated_by", "version", "updated_at"))
    logger.info(
        "contact.primary_set",
        extra={"object_id": str(contact.pk), "outcome": "success"},
    )
    return contact


def contact_differences(contact, incoming):
    """Fields that would change. Callers must choose each one explicitly."""
    differences = []
    comparisons = (
        ("first_name", contact.first_name, incoming.get("first_name")),
        ("last_name", contact.last_name, incoming.get("last_name")),
        ("email", contact.email, incoming.get("email")),
        ("title", contact.title, incoming.get("title")),
    )
    for field, current, proposed in comparisons:
        proposed_text = "" if proposed in (None, "") else str(proposed).strip()
        if proposed_text and proposed_text != (current or ""):
            differences.append(
                {"field": field, "current": current or "", "proposed": proposed_text}
            )
    return differences


@transaction.atomic
def set_account_parent(*, actor, account, parent_id):
    require_action(actor, "account", "U", object_id=account.pk)
    parent = None if not parent_id else get_scoped(Account, actor, parent_id)
    locked = Account.objects.select_for_update().get(pk=account.pk)
    assert_account_parent(locked, parent)
    locked.parent = parent
    locked.updated_by = actor
    locked.version += 1
    locked.save(update_fields=("parent", "updated_by", "version", "updated_at"))
    return locked


@transaction.atomic
def set_reports_to(*, actor, contact, manager_id):
    require_action(actor, "contact", "U", object_id=contact.pk)
    manager = None if not manager_id else get_scoped(Contact, actor, manager_id)
    locked = Contact.objects.select_for_update().get(pk=contact.pk)
    assert_reports_to(
        locked,
        manager,
        allow_cross_account=actor.is_company_admin,
    )
    locked.reports_to = manager
    locked.updated_by = actor
    locked.version += 1
    locked.save(update_fields=("reports_to", "updated_by", "version", "updated_at"))
    return locked


@transaction.atomic
def update_account(*, actor, account_id, version, data, request_id=""):
    """Change the fields a person can edit. The id stays with the application."""
    require_action(actor, "account", "U", object_id=account_id)
    account = get_scoped(
        Account, actor, account_id, for_update=True, related=("owner", "parent")
    )
    if require_version(version) != account.version:
        raise VersionConflict
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError({"name": "This field is required."})
    account_type = str(data.get("account_type") or "").strip()
    if account_type not in Account.Type.values:
        raise ValidationError({"account_type": "Choose an account type."})
    parent = None
    if data.get("parent"):
        parent = get_scoped(Account, actor, data.get("parent"))
    assert_account_parent(account, parent)
    website, domain = clean_website(data.get("website_url") or "")
    status = str(data.get("status") or account.status).strip()
    if status not in Account.Status.values:
        raise ValidationError({"status": "Choose a status."})
    before = account_snapshot(account)
    account.name = name[:200]
    account.name_normalized = normalize_name(name)[:200]
    account.account_type = account_type
    account.parent = parent
    account.website_url = website
    account.website_domain = domain
    account.industry = clean_optional_key(
        "INDUSTRY", data.get("industry") or "", "industry"
    )
    account.phone = _phone(data.get("phone"))
    account.address = address_from_mapping(data, current=account.address)
    account.status = status
    account.notes = _notes(data.get("notes"))
    if data.get("owner"):
        account.owner = clean_owner(actor, data.get("owner"), object_key="account")
    account.updated_by = actor
    account.version += 1
    account.full_clean()
    account.save()
    _audit(
        actor,
        "account.updated",
        account,
        request_id,
        before,
        account_snapshot(account),
    )
    return account


@transaction.atomic
def update_contact(*, actor, contact_id, version, data, request_id=""):
    """Change the fields a person can edit. The id stays with the application."""
    require_action(actor, "contact", "U", object_id=contact_id)
    contact = get_scoped(
        Contact,
        actor,
        contact_id,
        for_update=True,
        related=("owner", "account", "reports_to"),
    )
    if require_version(version) != contact.version:
        raise VersionConflict
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()
    missing = {}
    if not first_name:
        missing["first_name"] = "This field is required."
    if not last_name:
        missing["last_name"] = "This field is required."
    if missing:
        raise ValidationError(missing)
    account = get_scoped(Account, actor, data.get("account") or contact.account_id)
    reports_to = None
    if data.get("reports_to"):
        reports_to = get_scoped(Contact, actor, data.get("reports_to"))
    email = _email(data.get("email"))
    before = contact_snapshot(contact)
    contact.first_name = first_name[:80]
    contact.last_name = last_name[:80]
    contact.title = str(data.get("title") or "").strip()[:120]
    contact.email = email
    contact.email_normalized = email
    contact.work_phone = _phone(data.get("work_phone"), "work_phone")
    contact.mobile_phone = _phone(data.get("mobile_phone"), "mobile_phone")
    contact.address = address_from_mapping(data, current=contact.address)
    contact.account = account
    contact.notes = _notes(data.get("notes"))
    if data.get("owner"):
        contact.owner = clean_owner(actor, data.get("owner"), object_key="contact")
    assert_reports_to(
        contact,
        reports_to,
        allow_cross_account=actor.is_company_admin,
    )
    contact.reports_to = reports_to
    wants_primary = _checked(data.get("is_primary"))
    if wants_primary:
        Account.objects.select_for_update().get(pk=account.pk)
        Contact.objects.filter(account_id=account.pk, is_primary=True).exclude(
            pk=contact.pk
        ).update(is_primary=False)
    contact.is_primary = wants_primary
    contact.updated_by = actor
    contact.version += 1
    contact.full_clean()
    contact.save()
    _audit(
        actor,
        "contact.updated",
        contact,
        request_id,
        before,
        contact_snapshot(contact),
    )
    return contact


def _retire(record, actor, reason):
    record.deleted_at = datetime.now(UTC)
    record.deleted_by = actor
    record.delete_reason = clean_delete_reason(reason)
    record.updated_by = actor
    record.version += 1
    record.save()


@transaction.atomic
def delete_account(*, actor, account_id, version, delete_reason, request_id=""):
    """Soft-delete an account once its contacts, deals, and child accounts are gone."""
    from sales.models import Deal

    require_action(actor, "account", "D", object_id=account_id)
    account = get_scoped(Account, actor, account_id, for_update=True)
    if require_version(version) != account.version:
        raise VersionConflict
    if Account.objects.filter(parent=account).exists():
        raise ValidationError(
            {
                "detail": "Delete the child accounts before deleting this account.",
            }
        )
    if Contact.objects.filter(account=account).exists():
        raise ValidationError(
            {
                "detail": "Delete this account's contacts before deleting the account.",
            }
        )
    if Deal.objects.filter(account=account).exists():
        raise ValidationError(
            {"detail": "Delete this account's deals before deleting the account."}
        )
    before = account_snapshot(account)
    _retire(account, actor, delete_reason)
    _audit(
        actor,
        "account.deleted",
        account,
        request_id,
        before,
        account_snapshot(account),
    )
    return account


@transaction.atomic
def delete_contact(*, actor, contact_id, version, delete_reason, request_id=""):
    """Soft-delete a contact once deals and reporting lines no longer depend on it."""
    from sales.models import Deal

    require_action(actor, "contact", "D", object_id=contact_id)
    contact = get_scoped(Contact, actor, contact_id, for_update=True)
    if require_version(version) != contact.version:
        raise VersionConflict
    if Contact.objects.filter(reports_to=contact).exists():
        raise ValidationError(
            {
                "detail": ("Change who reports to this contact before deleting them."),
            }
        )
    if Deal.objects.filter(primary_contact=contact).exists():
        raise ValidationError(
            {
                "detail": "Remove this contact from deals before deleting them.",
            }
        )
    before = contact_snapshot(contact)
    _retire(contact, actor, delete_reason)
    _audit(
        actor,
        "contact.deleted",
        contact,
        request_id,
        before,
        contact_snapshot(contact),
    )
    return contact
