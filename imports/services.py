"""CSV preview, chunked commit, rollback, and scoped export."""

import csv
import io
import logging
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from accounts.models import Account, Contact
from accounts.services import (
    create_account,
    create_contact,
    mark_primary,
    normalize_name,
)
from audit.models import AuditEvent
from core.access import scoped
from core.policy import allows, deny
from core.taxonomy import active_keys
from core.validation import (
    ADDRESS_LIMITS,
    clean_address,
    clean_email,
    clean_external_id,
    clean_money,
    clean_owner,
    clean_phone,
    clean_website,
)
from imports.columns import COLUMNS, ENTITIES, POLICIES, columns_for
from imports.models import ImportBatch, ImportRow
from leads.models import Lead
from leads.services import create_lead, update_lead

logger = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 50_000
CHUNK_SIZE = 200
ERROR_SAMPLE = 100
ALLOWED_TYPES = {
    "",
    "text/csv",
    "application/csv",
    "text/plain",
    "application/vnd.ms-excel",
}


def can_import(user):
    return allows(user, "import", "C") or allows(user, "import", "A")


def require_import(user):
    if can_import(user):
        return
    deny(user, "import", "C", reason="missing_grant")


def _messages(exc):
    if hasattr(exc, "message_dict"):
        parts = []
        for field, items in exc.message_dict.items():
            parts.append(f"{field}: {', '.join(items)}")
        return "; ".join(parts)
    return "; ".join(exc.messages)


def _formula(value):
    text = str(value or "").strip()
    if not text:
        return False
    if text[0] in "=+@":
        return True
    if text[0] != "-":
        return False
    try:
        Decimal(text)
    except InvalidOperation:
        return True
    return False


def _header_key(value):
    return str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")


def _owner(actor, name, object_key):
    text = str(name or "").strip()
    if not text:
        return None
    from identity.models import User

    people = list(User.objects.filter(is_active=True, display_name__iexact=text)[:2])
    if not people:
        raise ValidationError({"owner": "No active user has that name."})
    if len(people) > 1:
        raise ValidationError({"owner": "More than one active user has that name."})
    return clean_owner(actor, people[0], object_key=object_key)


def _optional_bool(value, field):
    text = str(value or "").strip().casefold()
    if text == "":
        return None
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValidationError({field: "Use true or false."})


def _check_file(filename, content_type, content):
    name = str(filename or "").strip()
    if not name.lower().endswith(".csv"):
        raise ValidationError(
            {"file": "Upload a .csv file. Workbooks are not accepted yet."}
        )
    if str(content_type or "") not in ALLOWED_TYPES:
        raise ValidationError({"file": "Upload a CSV file."})
    if len(content) > MAX_BYTES:
        raise ValidationError({"file": "The file is larger than 25 MB."})
    if not content:
        raise ValidationError({"file": "The file is empty."})


def _decode(content):
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError({"file": "Save the file as UTF-8."}) from exc


def _table(text):
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(str(cell).strip() for cell in row):
            continue
        if str(row[0]).strip().startswith("#"):
            continue
        rows.append([str(cell).strip() for cell in row])
    if not rows:
        raise ValidationError({"file": "The file has no header row."})
    header = [_header_key(cell) for cell in rows[0]]
    if len(header) != len(set(header)):
        raise ValidationError({"file": "The header repeats a column."})
    data_rows = rows[1:]
    if len(data_rows) > MAX_ROWS:
        raise ValidationError({"file": "A file can contain 50,000 data rows."})
    return header, data_rows


def _cells(header, row):
    values = {key: "" for key in header}
    for index, key in enumerate(header):
        if index < len(row):
            values[key] = row[index]
    return values


def _required_headers(entity):
    return [column.key for column in columns_for(entity) if column.required]


def _check_headers(entity, header):
    missing = [key for key in _required_headers(entity) if key not in header]
    if missing:
        raise ValidationError(
            {"file": "Add these columns: " + ", ".join(missing) + "."}
        )


def _reject_formulas(cells):
    for key, value in cells.items():
        if key == "row_action":
            continue
        if _formula(value):
            raise ValidationError(
                {
                    key: (
                        "Cells cannot start with =, +, or @, "
                        "or a minus that is not a number."
                    )
                }
            )


def _cached_keys(cache, list_key):
    if list_key not in cache:
        cache[list_key] = active_keys(list_key)
    return cache[list_key]


def _required_key(cache, list_key, value, field):
    key = str(value or "").strip()
    if key not in _cached_keys(cache, list_key):
        raise ValidationError({field: "Select an active value."})
    return key


def _optional_key(cache, list_key, value, field):
    key = str(value or "").strip()
    if not key:
        return ""
    if key not in _cached_keys(cache, list_key):
        raise ValidationError({field: "Select an active value."})
    return key


def _text(value, field, limit, *, required=False):
    text = str(value or "").strip()
    if required and not text:
        raise ValidationError({field: "This field is required."})
    if len(text) > limit:
        raise ValidationError({field: f"Use {limit} characters or fewer."})
    return text


def _address_from_cells(cells):
    parts = {}
    for key, limit in ADDRESS_LIMITS.items():
        if cells.get(key, "") != "":
            parts[key] = _text(cells[key], key, limit)
    if not parts:
        return None
    return clean_address(parts)


def _merge_address(record, incoming):
    if not isinstance(incoming, dict):
        return record.address or {}
    merged = dict(record.address or {})
    merged.update(incoming)
    return clean_address(merged)


def _clean_lead(actor, cells, cache):
    _reject_formulas(cells)
    stage = cells.get("stage", "")
    if stage not in ("", "NEW"):
        raise ValidationError(
            {"stage": "Imported leads start at NEW. Leave stage blank."}
        )
    data = {
        "first_name": _text(
            cells.get("first_name", ""), "first_name", 80, required=True
        ),
        "last_name": _text(cells.get("last_name", ""), "last_name", 80, required=True),
        "company_name": _text(
            cells.get("company_name", ""), "company_name", 200, required=True
        ),
        "source": _required_key(
            cache, "LEAD_SOURCE", cells.get("source", ""), "source"
        ),
        "stage": "NEW",
    }
    email, _domain = clean_email(cells.get("email", ""))
    if not email:
        raise ValidationError({"email": "Enter an email address."})
    data["email"] = email
    for key in (
        "title",
        "website_url",
        "industry",
        "products_services",
        "company_size_band",
        "notes",
        "rating",
    ):
        if cells.get(key, "") != "":
            data[key] = cells[key]
    if cells.get("external_id", "") != "":
        data["external_id"] = clean_external_id(cells["external_id"])
    for key in ("work_phone", "mobile_phone"):
        if cells.get(key, "") != "":
            data[key] = clean_phone(cells[key], field=key)
    if cells.get("annual_revenue", "") != "":
        data["annual_revenue"] = clean_money(cells["annual_revenue"], "annual_revenue")
    address = _address_from_cells(cells)
    if address is not None:
        data["address"] = address
    if cells.get("rating", ""):
        data["rating"] = _required_key(cache, "LEAD_RATING", cells["rating"], "rating")
    if cells.get("industry", ""):
        data["industry"] = _optional_key(
            cache, "INDUSTRY", cells["industry"], "industry"
        )
    if cells.get("company_size_band", ""):
        data["company_size_band"] = _optional_key(
            cache, "COMPANY_SIZE", cells["company_size_band"], "company_size_band"
        )
    owner = _owner(actor, cells.get("owner", ""), "lead")
    if owner is not None:
        data["owner"] = owner
    return data


def _clean_account(actor, cells, cache):
    _reject_formulas(cells)
    account_type = cells.get("account_type", "")
    if account_type not in Account.Type.values:
        raise ValidationError({"account_type": "Choose an account type key."})
    data = {
        "name": cells.get("name", ""),
        "account_type": account_type,
    }
    if not str(data["name"]).strip():
        raise ValidationError({"name": "This field is required."})
    for key in ("website_url", "notes", "industry"):
        if cells.get(key, "") != "":
            data[key] = cells[key]
    if cells.get("industry", "") != "":
        data["industry"] = _optional_key(
            cache, "INDUSTRY", cells["industry"], "industry"
        )
    if cells.get("website_url", "") != "":
        clean_website(cells["website_url"])
    if cells.get("phone", "") != "":
        data["phone"] = clean_phone(cells["phone"])
    if cells.get("external_id", "") != "":
        data["external_id"] = clean_external_id(cells["external_id"])
    address = _address_from_cells(cells)
    if address is not None:
        data["address"] = address
    if cells.get("parent_external_id", "") != "":
        data["parent_external_id"] = clean_external_id(cells["parent_external_id"])
    owner = _owner(actor, cells.get("owner", ""), "account")
    if owner is not None:
        data["owner"] = owner
    return data


def _clean_contact(actor, cells, cache):
    del cache
    _reject_formulas(cells)
    if not cells.get("account_external_id", ""):
        raise ValidationError({"account_external_id": "This field is required."})
    data = {
        "account_external_id": clean_external_id(cells["account_external_id"]),
        "first_name": cells.get("first_name", ""),
        "last_name": cells.get("last_name", ""),
    }
    if not str(data["first_name"]).strip() or not str(data["last_name"]).strip():
        raise ValidationError(
            {
                "first_name": "This field is required.",
                "last_name": "This field is required.",
            }
        )
    for key in ("title", "notes"):
        if cells.get(key, "") != "":
            data[key] = cells[key]
    email, _domain = clean_email(cells.get("email", ""))
    if not email:
        raise ValidationError({"email": "Enter an email address."})
    data["email"] = email
    for key in ("work_phone", "mobile_phone"):
        if cells.get(key, "") != "":
            data[key] = clean_phone(cells[key], field=key)
    if cells.get("external_id", "") != "":
        data["external_id"] = clean_external_id(cells["external_id"])
    address = _address_from_cells(cells)
    if address is not None:
        data["address"] = address
    if cells.get("reports_to_external_id", "") != "":
        data["reports_to_external_id"] = clean_external_id(
            cells["reports_to_external_id"]
        )
    primary = _optional_bool(cells.get("is_primary", ""), "is_primary")
    if primary is not None:
        data["is_primary"] = primary
    owner = _owner(actor, cells.get("owner", ""), "contact")
    if owner is not None:
        data["owner"] = owner
    return data


CLEANERS = {
    "lead": _clean_lead,
    "account": _clean_account,
    "contact": _clean_contact,
}


def _model(entity):
    return {"lead": Lead, "account": Account, "contact": Contact}[entity]


def _index_existing(actor, entity, rows):
    model = _model(entity)
    external_ids = [row.get("external_id") for row in rows if row.get("external_id")]
    visible = {}
    hidden = set()
    if external_ids:
        for record in scoped(model.objects.all(), actor).filter(
            external_id__in=external_ids
        ):
            visible[record.external_id] = record.pk
        hidden = set(
            model.objects.filter(external_id__in=external_ids).values_list(
                "external_id", flat=True
            )
        ) - set(visible)
    emails = {}
    if entity in {"lead", "contact"}:
        wanted = []
        for row in rows:
            if row.get("email"):
                wanted.append(str(row["email"]).strip().lower())
        if wanted:
            for record in scoped(model.objects.all(), actor).filter(
                email_normalized__in=wanted
            ):
                emails.setdefault(record.email_normalized, record.pk)
    accounts = {}
    if entity == "account":
        domains = [
            row.get("website_domain") for row in rows if row.get("website_domain")
        ]
        names = [
            row.get("name_normalized") for row in rows if row.get("name_normalized")
        ]
        if domains:
            for record in scoped(model.objects.all(), actor).filter(
                website_domain__in=domains
            ):
                accounts.setdefault(("domain", record.website_domain), record.pk)
        if names:
            for record in scoped(model.objects.all(), actor).filter(
                name_normalized__in=names
            ):
                accounts.setdefault(("name", record.name_normalized), record.pk)
    known_accounts = {}
    known_contacts = {}
    account_ids = [
        row.get("account_external_id") for row in rows if row.get("account_external_id")
    ]
    if account_ids:
        for record in scoped(Account.objects.all(), actor).filter(
            external_id__in=account_ids
        ):
            known_accounts[record.external_id] = record.pk
    contact_ids = [
        row.get("reports_to_external_id")
        for row in rows
        if row.get("reports_to_external_id")
    ]
    parent_ids = [
        row.get("parent_external_id") for row in rows if row.get("parent_external_id")
    ]
    if parent_ids:
        for record in scoped(Account.objects.all(), actor).filter(
            external_id__in=parent_ids
        ):
            known_accounts[record.external_id] = record.pk
    if contact_ids:
        for record in scoped(Contact.objects.all(), actor).filter(
            external_id__in=contact_ids
        ):
            known_contacts[record.external_id] = record.pk
    return {
        "visible": visible,
        "hidden": hidden,
        "emails": emails,
        "accounts": accounts,
        "known_accounts": known_accounts,
        "known_contacts": known_contacts,
    }


def _enrich(entity, data):
    extra = dict(data)
    if entity == "account":
        website, domain = clean_website(data.get("website_url") or "")
        extra["website_domain"] = domain
        extra["website_url"] = website
        extra["name_normalized"] = normalize_name(data.get("name") or "")
    if entity in {"lead", "contact"} and data.get("email"):
        email, _domain = clean_email(data["email"])
        extra["email"] = email
    return extra


def _match(entity, data, indexes, pending):
    external_id = data.get("external_id") or ""
    if external_id and external_id in indexes["hidden"]:
        raise ValidationError(
            {"external_id": "That external ID belongs to a record you cannot change."}
        )
    if external_id and external_id in pending["external_id"]:
        return pending["external_id"][external_id]
    if external_id and external_id in indexes["visible"]:
        return {"pk": indexes["visible"][external_id], "row": None}
    if entity in {"lead", "contact"} and data.get("email"):
        email = str(data["email"]).strip().lower()
        if email in pending["email"]:
            return pending["email"][email]
        if email in indexes["emails"]:
            return {"pk": indexes["emails"][email], "row": None}
    if entity == "account":
        domain = data.get("website_domain") or ""
        if domain and ("domain", domain) in pending["account"]:
            return pending["account"][("domain", domain)]
        if domain and ("domain", domain) in indexes["accounts"]:
            return {"pk": indexes["accounts"][("domain", domain)], "row": None}
        name = data.get("name_normalized") or ""
        if name and ("name", name) in pending["account"]:
            return pending["account"][("name", name)]
        if name and ("name", name) in indexes["accounts"]:
            return {"pk": indexes["accounts"][("name", name)], "row": None}
    return None


def _remember(entity, data, row_number, pending):
    pointer = {"pk": None, "row": row_number}
    external_id = data.get("external_id") or ""
    if external_id:
        pending["external_id"][external_id] = pointer
    if entity in {"lead", "contact"} and data.get("email"):
        pending["email"][str(data["email"]).strip().lower()] = pointer
    if entity == "account":
        if data.get("website_domain"):
            pending["account"][("domain", data["website_domain"])] = pointer
        if data.get("name_normalized"):
            pending["account"][("name", data["name_normalized"])] = pointer
    if entity == "account" and external_id:
        pending["known_accounts"][external_id] = pointer
    if entity == "contact" and external_id:
        pending["known_contacts"][external_id] = pointer


def _check_links(entity, data, indexes, pending, row_number):
    if entity == "account" and data.get("parent_external_id"):
        parent_id = data["parent_external_id"]
        if parent_id == data.get("external_id"):
            raise ValidationError(
                {"parent_external_id": "An account cannot be its own parent."}
            )
        known = (
            parent_id in indexes["known_accounts"]
            or parent_id in pending["known_accounts"]
        )
        earlier = pending["known_accounts"].get(parent_id)
        if earlier and earlier["row"] == row_number:
            known = False
        if not known:
            raise ValidationError(
                {
                    "parent_external_id": (
                        "The parent account must already exist or appear earlier "
                        "in this file."
                    )
                }
            )
    if entity == "contact":
        account_id = data["account_external_id"]
        if account_id not in indexes["known_accounts"]:
            raise ValidationError(
                {"account_external_id": ("Import the account before this contact.")}
            )
        manager_id = data.get("reports_to_external_id") or ""
        if manager_id:
            known = (
                manager_id in indexes["known_contacts"]
                or manager_id in pending["known_contacts"]
            )
            if not known:
                raise ValidationError(
                    {
                        "reports_to_external_id": (
                            "That contact must already exist or be on an earlier row."
                        )
                    }
                )


def plan_rows(actor, entity, policy, text):
    header, data_rows = _table(text)
    _check_headers(entity, header)
    cleaner = CLEANERS[entity]
    cache = {}
    prepared = []
    for offset, row in enumerate(data_rows, start=2):
        cells = _cells(header, row)
        if cells.get("row_action", "").casefold() == "example":
            continue
        try:
            data = _enrich(entity, cleaner(actor, cells, cache))
            prepared.append({"row_number": offset, "data": data, "message": ""})
        except ValidationError as exc:
            prepared.append(
                {
                    "row_number": offset,
                    "data": {},
                    "outcome": "error",
                    "message": _messages(exc),
                    "match": None,
                }
            )
    indexes = _index_existing(
        actor,
        entity,
        [item["data"] for item in prepared if item.get("data")],
    )
    pending = {
        "external_id": {},
        "email": {},
        "account": {},
        "known_accounts": {},
        "known_contacts": {},
    }
    plans = []
    for item in prepared:
        if item.get("outcome") == "error":
            plans.append(item)
            continue
        data = item["data"]
        try:
            _check_links(entity, data, indexes, pending, item["row_number"])
            match = _match(entity, data, indexes, pending)
        except ValidationError as exc:
            plans.append(
                {
                    "row_number": item["row_number"],
                    "data": data,
                    "outcome": "error",
                    "message": _messages(exc),
                    "match": None,
                }
            )
            continue
        external_id = data.get("external_id") or ""
        external_taken = bool(
            external_id
            and (
                external_id in indexes["visible"]
                or external_id in pending["external_id"]
            )
        )
        if external_taken and policy == "create":
            plans.append(
                {
                    "row_number": item["row_number"],
                    "data": data,
                    "outcome": "error",
                    "message": (
                        "external_id: That id already exists. "
                        "Use Skip or Update to reuse it."
                    ),
                    "match": match,
                }
            )
            continue
        if match is None or (policy == "create" and not external_taken):
            outcome = "create"
        elif policy == "skip":
            outcome = "skip"
        else:
            outcome = "update"
        if outcome == "create":
            _remember(entity, data, item["row_number"], pending)
        plans.append(
            {
                "row_number": item["row_number"],
                "data": data,
                "outcome": outcome,
                "message": "",
                "match": match,
            }
        )
    return plans


def _summary(plans):
    errors = [
        {"row": plan["row_number"], "message": plan["message"]}
        for plan in plans
        if plan["outcome"] == "error"
    ]
    return {
        "row_count": len(plans),
        "error_count": len(errors),
        "create_count": sum(plan["outcome"] == "create" for plan in plans),
        "update_count": sum(plan["outcome"] == "update" for plan in plans),
        "skip_count": sum(plan["outcome"] == "skip" for plan in plans),
        "errors": errors[:ERROR_SAMPLE],
    }


def _policy(value):
    policy = str(value or "skip").strip().casefold()
    if policy not in POLICIES:
        raise ValidationError({"policy": "Choose skip, update, or create."})
    return policy


def _entity(value):
    entity = str(value or "").strip().casefold()
    if entity not in ENTITIES:
        raise ValidationError({"entity": "Choose leads, accounts, or contacts."})
    return entity


def _key(value):
    key = str(value or "").strip()
    if not key:
        return ""
    if len(key) > 64 or not key.replace("-", "").replace("_", "").isalnum():
        raise ValidationError(
            {"idempotency_key": ("Use letters, numbers, hyphens, or underscores.")}
        )
    return key


def preview_import(
    *,
    actor,
    entity,
    upload_name,
    content_type,
    content,
    policy,
    idempotency_key="",
    request_id="",
):
    require_import(actor)
    entity = _entity(entity)
    policy = _policy(policy)
    key = _key(idempotency_key)
    _check_file(upload_name, content_type, content)
    plans = plan_rows(actor, entity, policy, _decode(content))
    summary = _summary(plans)
    if key:
        existing = ImportBatch.objects.filter(actor=actor, idempotency_key=key).first()
        if existing and existing.status != ImportBatch.Status.PREVIEW:
            return existing
        batch = existing
    else:
        batch = None
    if batch is None:
        batch = ImportBatch(
            actor=actor,
            entity=entity,
            policy=policy,
            status=ImportBatch.Status.PREVIEW,
            idempotency_key=key,
            filename=str(upload_name)[:255],
            request_id=request_id,
            summary=summary,
        )
        batch.payload.save(str(upload_name)[:255], ContentFile(content), save=False)
        batch.save()
    else:
        batch.entity = entity
        batch.policy = policy
        batch.filename = str(upload_name)[:255]
        batch.summary = summary
        batch.payload.save(str(upload_name)[:255], ContentFile(content), save=False)
        batch.save()
    logger.info(
        "import.previewed %s rows=%s errors=%s",
        entity,
        summary["row_count"],
        summary["error_count"],
    )
    return batch


def _payload_text(batch):
    batch.payload.open("rb")
    try:
        content = batch.payload.read()
    finally:
        batch.payload.close()
    return _decode(content)


def _lead_snapshot(lead):
    revenue = None if lead.annual_revenue is None else str(lead.annual_revenue)
    return {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "company_name": lead.company_name,
        "source": lead.source,
        "title": lead.title,
        "email": lead.email,
        "work_phone": lead.work_phone,
        "mobile_phone": lead.mobile_phone,
        "address": lead.address or {},
        "website_url": lead.website_url,
        "industry": lead.industry,
        "products_services": lead.products_services,
        "company_size_band": lead.company_size_band,
        "annual_revenue": revenue,
        "rating": lead.rating,
        "owner": lead.owner_id,
        "notes": lead.notes,
    }


def _account_snapshot(account):
    return {
        "name": account.name,
        "account_type": account.account_type,
        "parent_id": None if account.parent_id is None else str(account.parent_id),
        "website_url": account.website_url,
        "phone": account.phone,
        "address": account.address or {},
        "industry": account.industry,
        "owner": account.owner_id,
        "notes": account.notes,
    }


def _contact_snapshot(contact):
    return {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "title": contact.title,
        "email": contact.email,
        "work_phone": contact.work_phone,
        "mobile_phone": contact.mobile_phone,
        "address": contact.address or {},
        "account_id": str(contact.account_id),
        "reports_to_id": None
        if contact.reports_to_id is None
        else str(contact.reports_to_id),
        "owner": contact.owner_id,
        "notes": contact.notes,
        "is_primary": contact.is_primary,
    }


def _changes(data):
    skipped = {
        "website_domain",
        "name_normalized",
        "parent_external_id",
        "account_external_id",
        "reports_to_external_id",
        "stage",
        "external_id",
    }
    return {
        key: value
        for key, value in data.items()
        if key not in skipped and value not in (None, "")
    }


def _apply_create(actor, entity, data, request_id, made):
    payload = _changes(data)
    if data.get("external_id"):
        payload["external_id"] = data["external_id"]
    if entity == "lead":
        payload["stage"] = "NEW"
        return create_lead(actor=actor, data=payload, request_id=request_id)
    if entity == "account":
        parent_key = data.get("parent_external_id") or ""
        if parent_key:
            parent = made["accounts"].get(parent_key)
            if parent is None:
                parent = scoped(Account.objects.all(), actor).get(
                    external_id=parent_key
                )
            payload["parent"] = str(parent.pk)
        return create_account(actor=actor, data=payload, request_id=request_id)
    account_key = data["account_external_id"]
    account = made["accounts"].get(account_key)
    if account is None:
        account = scoped(Account.objects.all(), actor).get(external_id=account_key)
    payload["account"] = str(account.pk)
    manager_key = data.get("reports_to_external_id") or ""
    if manager_key:
        manager = made["contacts"].get(manager_key)
        if manager is None:
            manager = scoped(Contact.objects.all(), actor).get(external_id=manager_key)
        payload["reports_to"] = str(manager.pk)
    if data.get("is_primary") is True:
        payload["is_primary"] = True
    return create_contact(actor=actor, data=payload, request_id=request_id)


def _apply_update(actor, entity, plan, request_id, made):
    match = plan["match"] or {}
    if match.get("row"):
        record = made["rows"][match["row"]]
    else:
        record = _model(entity).objects.select_for_update().get(pk=match["pk"])
    if entity == "lead":
        before = _lead_snapshot(record)
        changes = _changes(plan["data"])
        if "address" in changes:
            changes["address"] = _merge_address(record, changes["address"])
        updated = update_lead(
            actor=actor,
            lead_id=record.pk,
            version=record.version,
            data=changes,
            request_id=request_id,
        )
        return updated, before
    if entity == "account":
        before = _account_snapshot(record)
        changes = _changes(plan["data"])
        record.name = changes.get("name", record.name)
        record.name_normalized = normalize_name(record.name)[:200]
        if "account_type" in changes:
            record.account_type = changes["account_type"]
        if "website_url" in changes:
            website, domain = clean_website(changes["website_url"])
            record.website_url = website
            record.website_domain = domain
        if "phone" in changes:
            record.phone = clean_phone(changes["phone"])
        if "industry" in changes:
            record.industry = changes["industry"]
        if "notes" in changes:
            record.notes = changes["notes"]
        if "address" in changes:
            record.address = _merge_address(record, changes["address"])
        if "owner" in changes:
            record.owner = changes["owner"]
        parent_key = plan["data"].get("parent_external_id") or ""
        if parent_key:
            parent = made["accounts"].get(parent_key) or scoped(
                Account.objects.all(), actor
            ).get(external_id=parent_key)
            record.parent = parent
        record.updated_by = actor
        record.version += 1
        record.full_clean()
        record.save()
        AuditEvent.objects.create(
            actor=actor,
            action="account.updated",
            object_type="accounts.account",
            object_id=str(record.pk),
            before_json=before,
            after_json={"external_id": record.external_id, "version": record.version},
            request_id=request_id,
            source="import",
        )
        return record, before
    before = _contact_snapshot(record)
    changes = _changes(plan["data"])
    for field in ("first_name", "last_name", "title", "notes"):
        if field in changes:
            setattr(record, field, changes[field])
    for field in ("work_phone", "mobile_phone"):
        if field in changes:
            setattr(record, field, clean_phone(changes[field], field=field))
    if "address" in changes:
        record.address = _merge_address(record, changes["address"])
    if "email" in changes:
        email, _domain = clean_email(changes["email"])
        record.email = email
        record.email_normalized = email
    if "owner" in changes:
        record.owner = changes["owner"]
    account_key = plan["data"].get("account_external_id") or ""
    if account_key:
        account = made["accounts"].get(account_key) or scoped(
            Account.objects.all(), actor
        ).get(external_id=account_key)
        record.account = account
    record.updated_by = actor
    record.version += 1
    record.full_clean()
    record.save()
    if plan["data"].get("is_primary") is True:
        mark_primary(actor=actor, contact=record, request_id=request_id)
    AuditEvent.objects.create(
        actor=actor,
        action="contact.updated",
        object_type="accounts.contact",
        object_id=str(record.pk),
        before_json=before,
        after_json={"external_id": record.external_id, "version": record.version},
        request_id=request_id,
        source="import",
    )
    return record, before


def _store_made(entity, record, made):
    made["rows_by_id"][record.pk] = record
    made["external"][record.external_id] = record
    if entity == "account":
        made["accounts"][record.external_id] = record
    if entity == "contact":
        made["contacts"][record.external_id] = record


def commit_import(*, actor, batch_id, request_id=""):
    require_import(actor)
    batch = ImportBatch.objects.get(pk=batch_id, actor=actor)
    if batch.status == ImportBatch.Status.COMMITTED:
        return batch
    if batch.status == ImportBatch.Status.ROLLED_BACK:
        raise ValidationError({"batch": "This import was rolled back."})
    plans = plan_rows(actor, batch.entity, batch.policy, _payload_text(batch))
    done = set(
        batch.rows.filter(outcome__in=("created", "updated", "skipped")).values_list(
            "row_number", flat=True
        )
    )
    made = {
        "rows": {},
        "accounts": {},
        "contacts": {},
        "external": {},
        "rows_by_id": {},
    }
    pending = [plan for plan in plans if plan["row_number"] not in done]
    try:
        for start in range(0, len(pending), CHUNK_SIZE):
            with transaction.atomic():
                for plan in pending[start : start + CHUNK_SIZE]:
                    _commit_one(actor, batch, plan, request_id, made)
    except Exception as exc:
        batch.status = ImportBatch.Status.INCOMPLETE
        batch.summary = {
            **_summary(plans),
            "failure": str(exc)[:500],
        }
        batch.save(update_fields=("status", "summary"))
        logger.exception("import.incomplete %s", batch.pk)
        return batch
    batch.status = ImportBatch.Status.COMMITTED
    batch.committed_at = timezone.now()
    batch.summary = _summary(plans)
    batch.save(update_fields=("status", "summary", "committed_at"))
    AuditEvent.objects.create(
        actor=actor,
        action="import.committed",
        object_type="import",
        object_id=str(batch.pk),
        before_json=None,
        after_json={
            "entity": batch.entity,
            "policy": batch.policy,
            "row_count": batch.summary["row_count"],
            "create_count": batch.summary["create_count"],
            "update_count": batch.summary["update_count"],
            "skip_count": batch.summary["skip_count"],
            "error_count": batch.summary["error_count"],
        },
        request_id=request_id,
        source="import",
    )
    return batch


def _commit_one(actor, batch, plan, request_id, made):
    outcome = plan["outcome"]
    record = None
    before = None
    message = plan.get("message") or ""
    try:
        if outcome == "create":
            record = _apply_create(actor, batch.entity, plan["data"], request_id, made)
            outcome = "created"
        elif outcome == "update":
            record, before = _apply_update(actor, batch.entity, plan, request_id, made)
            outcome = "updated"
        elif outcome == "error":
            outcome = "error"
        else:
            outcome = "skipped"
    except ValidationError as exc:
        outcome = "error"
        message = _messages(exc)
        record = None
    if record is not None:
        _store_made(batch.entity, record, made)
        made["rows"][plan["row_number"]] = record
    ImportRow.objects.create(
        batch=batch,
        row_number=plan["row_number"],
        outcome=outcome,
        object_id="" if record is None else str(record.pk),
        external_id="" if record is None else record.external_id,
        before_json=before,
        after_version=None if record is None else record.version,
        message=message,
    )


def _owned_batch(actor, batch_id):
    try:
        batch = ImportBatch.objects.get(pk=batch_id)
    except ImportBatch.DoesNotExist as exc:
        raise Http404 from exc
    if batch.actor_id != actor.pk and not allows(actor, "import", "A"):
        raise Http404
    return batch


def rollback_import(*, actor, batch_id, request_id=""):
    require_import(actor)
    batch = _owned_batch(actor, batch_id)
    if batch.status not in {
        ImportBatch.Status.COMMITTED,
        ImportBatch.Status.INCOMPLETE,
    }:
        raise ValidationError({"batch": "Only a committed import can be rolled back."})
    conflicts = 0
    reverted = 0
    model = _model(batch.entity)
    with transaction.atomic():
        for row in batch.rows.select_for_update().filter(
            outcome__in=("created", "updated")
        ):
            try:
                record = model.all_objects.select_for_update().get(pk=row.object_id)
            except model.DoesNotExist:
                row.outcome = "conflict"
                row.message = "The record is no longer available."
                row.save(update_fields=("outcome", "message"))
                conflicts += 1
                continue
            if record.version != row.after_version or (
                row.outcome == "created" and record.deleted_at is not None
            ):
                row.outcome = "conflict"
                row.message = "Changed after import, so this row was left in place."
                row.save(update_fields=("outcome", "message"))
                conflicts += 1
                continue
            if row.outcome == "created":
                record.deleted_at = timezone.now()
                record.deleted_by = actor
                record.delete_reason = "Import rolled back"
                record.updated_by = actor
                record.version += 1
                record.save()
            else:
                _restore(actor, batch.entity, record, row.before_json or {})
            AuditEvent.objects.create(
                actor=actor,
                action="import.row_rolled_back",
                object_type=model._meta.label_lower,
                object_id=str(record.pk),
                before_json={"version": row.after_version},
                after_json={"version": record.version},
                request_id=request_id,
                source="import",
            )
            row.outcome = "rolled_back"
            row.save(update_fields=("outcome",))
            reverted += 1
        batch.status = ImportBatch.Status.ROLLED_BACK
        batch.summary = {
            **batch.summary,
            "reverted": reverted,
            "conflicts": conflicts,
        }
        batch.save(update_fields=("status", "summary"))
        AuditEvent.objects.create(
            actor=actor,
            action="import.rolled_back",
            object_type="import",
            object_id=str(batch.pk),
            before_json=None,
            after_json={"reverted": reverted, "conflicts": conflicts},
            request_id=request_id,
            source="import",
        )
    return batch


def _restore(actor, entity, record, before):
    if entity == "lead":
        update_lead(
            actor=actor,
            lead_id=record.pk,
            version=record.version,
            data=before,
            request_id="rollback",
        )
        return
    if entity == "account":
        record.name = before.get("name", record.name)
        record.name_normalized = normalize_name(record.name)[:200]
        record.account_type = before.get("account_type", record.account_type)
        record.website_url = before.get("website_url", record.website_url)
        _website, domain = clean_website(record.website_url)
        record.website_domain = domain
        record.phone = before.get("phone", record.phone)
        record.industry = before.get("industry", record.industry)
        record.notes = before.get("notes", record.notes)
        if before.get("owner"):
            record.owner_id = before["owner"]
        record.parent_id = before.get("parent_id") or None
        if "address" in before:
            record.address = before.get("address") or {}
    else:
        record.first_name = before.get("first_name", record.first_name)
        record.last_name = before.get("last_name", record.last_name)
        record.title = before.get("title", record.title)
        record.work_phone = before.get("work_phone", record.work_phone)
        record.mobile_phone = before.get("mobile_phone", record.mobile_phone)
        record.notes = before.get("notes", record.notes)
        email, _domain = clean_email(before.get("email") or "")
        record.email = email
        record.email_normalized = email
        if before.get("owner"):
            record.owner_id = before["owner"]
        if before.get("account_id"):
            record.account_id = before["account_id"]
        record.reports_to_id = before.get("reports_to_id") or None
        record.is_primary = bool(before.get("is_primary"))
        if "address" in before:
            record.address = before.get("address") or {}
    record.updated_by = actor
    record.version += 1
    record.save()


def escape_cell(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


EXPORT_IDS = {
    "lead": ("id",),
    "account": ("id",),
    "contact": ("id", "account_id"),
}


def export_csv(*, actor, entity):
    entity = _entity(entity)
    from core.policy import require_action

    require_action(actor, entity, "X")
    columns = [
        *EXPORT_IDS[entity],
        *[column.key for column in COLUMNS[entity] if column.key != "row_action"],
    ]
    model = _model(entity)
    queryset = scoped(model.objects.all(), actor)
    if entity == "account":
        queryset = queryset.select_related("owner", "parent")
    elif entity == "contact":
        queryset = queryset.select_related("owner", "account", "reports_to")
    else:
        queryset = queryset.select_related("owner")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    count = 0
    for record in queryset.order_by("created_at"):
        writer.writerow(
            [escape_cell(_export_value(entity, record, key)) for key in columns]
        )
        count += 1
    AuditEvent.objects.create(
        actor=actor,
        action="export.completed",
        object_type=model._meta.label_lower,
        object_id=entity,
        before_json=None,
        after_json={"entity": entity, "fields": columns, "row_count": count},
        request_id="",
        source="export",
    )
    return buffer.getvalue()


def _export_value(entity, record, key):
    if key == "id":
        return str(record.pk)
    if key == "account_id":
        return str(record.account_id)
    if key == "owner":
        return record.owner.display_name
    if key == "parent_external_id":
        return "" if record.parent_id is None else record.parent.external_id
    if key == "account_external_id":
        return record.account.external_id
    if key == "reports_to_external_id":
        return "" if record.reports_to_id is None else record.reports_to.external_id
    if key == "is_primary":
        return "true" if record.is_primary else "false"
    if key == "annual_revenue" and record.annual_revenue is not None:
        return format(record.annual_revenue, "f")
    if key in ADDRESS_LIMITS:
        return (record.address or {}).get(key, "")
    value = getattr(record, key, "")
    return "" if value is None else value
