"""Calculated ages and readable durations. Nothing here is stored."""

from django.utils import timezone


def duration_phrase(seconds):
    """Turn a stored duration into a short phrase."""
    total = max(int(seconds or 0), 0)
    if total < 60:
        return "less than a minute"
    minutes, _remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days} day" if days == 1 else f"{days} days")
    if hours and days < 7:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    if minutes and not days:
        parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
    return ", ".join(parts)


def elapsed_phrase(start, now=None):
    """Describe how long ago an aware timestamp was."""
    if start is None:
        return "—"
    current = now or timezone.now()
    return duration_phrase(int((current - start).total_seconds()))


def age_days(start, now=None):
    if start is None:
        return None
    current = now or timezone.now()
    return max((current - start).days, 0)
