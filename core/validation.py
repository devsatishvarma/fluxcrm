"""Shared parsing for taxonomy, money, and record identity."""

import re
import uuid
from datetime import UTC
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.taxonomy import active_keys, known_keys
from identity.models import User

EXTERNAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MONEY_LIMIT = Decimal("9999999999999999.99")


def new_external_id():
    return uuid.uuid4().hex


def clean_external_id(value, *, current=None):
    if value in (None, ""):
        return current or new_external_id()
    external_id = str(value).strip()
    if current is not None and external_id != current:
        raise ValidationError({"external_id": "The external ID cannot change."})
    if not EXTERNAL_ID_PATTERN.fullmatch(external_id):
        raise ValidationError(
            {"external_id": "Use letters, numbers, hyphens, or underscores."}
        )
    return external_id


def clean_optional_key(list_key, value, field):
    if value in (None, ""):
        return ""
    key = str(value).strip()
    if key not in active_keys(list_key):
        raise ValidationError({field: "Select an active value."})
    return key


def clean_required_key(list_key, value, field):
    key = clean_optional_key(list_key, value, field)
    if not key:
        raise ValidationError({field: "This field is required."})
    return key


def clean_known_key(list_key, value, field):
    key = str(value).strip()
    if key not in known_keys(list_key):
        raise ValidationError({field: "Unknown value."})
    return key


def clean_money(value, field="amount"):
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({field: "Enter a valid amount."}) from exc
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise ValidationError({field: "Use at most two decimal places."})
    if amount < 0 or amount > MONEY_LIMIT:
        raise ValidationError({field: "Enter an amount from 0 through 16 digits."})
    return amount.quantize(Decimal("0.01"))


def clean_currency(value):
    currency = str(value or "").strip().upper()
    if currency != "USD":
        raise ValidationError({"currency": "Phase 2 supports USD only."})
    return currency


def clean_email(value):
    if value in (None, ""):
        return "", ""
    email = str(value).strip().lower()
    try:
        validate_email(email)
    except ValidationError as exc:
        raise ValidationError({"email": "Enter a valid email address."}) from exc
    return email, email.split("@", 1)[1]


def clean_website(value):
    if value in (None, ""):
        return "", ""
    raw = str(value).strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or " " in raw:
        raise ValidationError({"website_url": "Enter a valid website."})
    return raw if "://" in raw else f"https://{raw}", host


def clean_date(value, field):
    if value in (None, ""):
        return None
    if hasattr(value, "year") and not hasattr(value, "hour"):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValidationError({field: "Enter a valid date."})
    return parsed


def clean_datetime(value, field):
    if value in (None, ""):
        return None
    if hasattr(value, "tzinfo"):
        if timezone.is_naive(value):
            return timezone.make_aware(value, UTC)
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError({field: "Enter a valid date and time."})
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, UTC)
    return parsed


def clean_owner(actor, value):
    if value in (None, ""):
        return actor
    if isinstance(value, User):
        owner = value if value.is_active else None
        if owner is None:
            raise ValidationError({"owner": "Select an active user."})
    else:
        try:
            owner = User.objects.get(pk=int(value), is_active=True)
        except (TypeError, ValueError, User.DoesNotExist) as exc:
            raise ValidationError({"owner": "Select an active user."}) from exc
    if not actor.is_company_admin and owner.pk != actor.pk:
        raise ValidationError({"owner": "You can only assign records to yourself."})
    return owner


def require_version(value):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"version": "Provide the record version."}) from exc


def clean_delete_reason(value):
    reason = str(value or "").strip()
    if len(reason) < 3:
        raise ValidationError(
            {"delete_reason": "Enter a delete reason of at least 3 characters."}
        )
    if len(reason) > 200:
        raise ValidationError({"delete_reason": "Use 200 characters or fewer."})
    return reason


def add_form_errors(form, exc: ValidationError):
    if getattr(exc, "error_dict", None):
        for field, errors in exc.error_dict.items():
            target = field if field in form.fields else None
            for error in errors:
                form.add_error(target, getattr(error, "message", error))
        return
    form.add_error(None, exc)
