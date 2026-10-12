from django import template

from core.display import duration_phrase, elapsed_phrase

register = template.Library()

CHOICE_LABELS = {
    "HOT": "Hot",
    "WARM": "Warm",
    "COLD": "Cold",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
}


@register.filter
def elapsed(value):
    return elapsed_phrase(value)


@register.filter
def duration(value):
    return duration_phrase(value)


@register.filter
def choice_label(value):
    return CHOICE_LABELS.get(value, value or "—")
