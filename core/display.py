"""Calculated ages and readable durations. Nothing here is stored."""

from django.utils import timezone


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
