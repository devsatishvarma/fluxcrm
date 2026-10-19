"""Calculated ages and readable durations. Nothing here is stored."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import timezone


def format_phone(value, *, empty="—"):
    """Show a stored phone as (XXX) XXX-XXXX."""
    text = str(value or "").strip()
    if not text:
        return empty
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return text
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def format_whole(value):
    """Show a stored number with no decimal places."""
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    return str(int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def format_address(value):
    """Show street, city, state, postal code, and country on one line."""
    if not isinstance(value, dict):
        return "—"
    street = str(value.get("street") or "").strip()
    city = str(value.get("city") or "").strip()
    region = str(value.get("region") or "").strip()
    postal_code = str(value.get("postal_code") or "").strip()
    country = str(value.get("country") or "").strip()
    locality = " ".join(part for part in (region, postal_code) if part)
    city_line = ", ".join(part for part in (city, locality) if part)
    text = ", ".join(part for part in (street, city_line, country) if part)
    return text or "—"


def format_money(value):
    """Show a stored amount as whole dollars: $ 1,234,567."""
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    rounded = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    sign = "-" if rounded < 0 else ""
    return f"{sign}$ {abs(rounded):,}"


def day_phrase(days):
    """Show an age as whole days, with no hours or minutes."""
    if days is None:
        return "—"
    count = max(int(days), 0)
    if count == 1:
        return "1 day"
    return f"{count} days"


def duration_phrase(seconds):
    """Turn a stored duration into whole days."""
    return day_phrase(max(int(seconds or 0), 0) // 86400)


def elapsed_phrase(start, now=None):
    """Describe how many whole days have passed since a timestamp."""
    return day_phrase(age_days(start, now))


def age_days(start, now=None):
    if start is None:
        return None
    current = now or timezone.now()
    return max((current - start).days, 0)
