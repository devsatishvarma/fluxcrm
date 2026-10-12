"""Account and contact rules shared by the pages and the API."""

import logging
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from accounts.models import Account, Contact
from audit.models import AuditEvent
from core.access import get_scoped
from core.validation import clean_email, clean_external_id, clean_owner, clean_website

logger = logging.getLogger(__name__)
CONVERTIBLE_ACCOUNT_TYPES = {Account.Type.CUSTOMER, Account.Type.PROSPECT}


def contacts_for_user(user):
    """Contacts on accounts this person can open, plus contacts they own."""
    queryset = Contact.objects.select_related("account", "owner")
    if getattr(user, "is_company_admin", False):
        return queryset
    return queryset.filter(Q(owner=user) | Q(account__owner=user))


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


def _audit(actor, action, instance, request_id):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        before_json=None,
        after_json={"external_id": instance.external_id, "version": instance.version},
        request_id=request_id,
        source="web",
    )
    logger.info(action, extra={"object_id": str(instance.pk), "outcome": "success"})


@transaction.atomic
def create_account(*, actor, data, request_id=""):
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
    account = Account(
        external_id=clean_external_id(data.get("external_id")),
        name=name[:200],
        name_normalized=normalize_name(name)[:200],
        account_type=account_type,
        parent=parent,
        website_url=website,
        website_domain=domain,
        phone=str(data.get("phone") or "").strip()[:40],
        owner=clean_owner(actor, data.get("owner")),
        notes=str(data.get("notes") or "").strip(),
        created_by=actor,
        updated_by=actor,
    )
    account.full_clean()
    account.save()
    _audit(actor, "account.created", account, request_id)
    return account


@transaction.atomic
def create_contact(*, actor, data, request_id=""):
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
    email, _domain = clean_email(data.get("email") or "")
    contact = Contact(
        external_id=clean_external_id(data.get("external_id")),
        first_name=first_name[:80],
        last_name=last_name[:80],
        title=str(data.get("title") or "").strip()[:120],
        email=email,
        email_normalized=email,
        account=account,
        reports_to=reports_to,
        owner=clean_owner(actor, data.get("owner") or account.owner_id),
        is_primary=False,
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
