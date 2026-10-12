from django import template

from core.display import duration_phrase, elapsed_phrase

register = template.Library()

TEMPERATURE_LABELS = {"HOT": "Hot", "WARM": "Warm", "COLD": "Cold"}


@register.filter
def elapsed(value):
    return elapsed_phrase(value)


@register.filter
def duration(value):
    return duration_phrase(value)


@register.filter
def temperature_label(value):
    return TEMPERATURE_LABELS.get(value, value or "—")
