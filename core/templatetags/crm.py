from django import template

from core.display import duration_phrase, elapsed_phrase, format_money

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
def money(value):
    return format_money(value)


@register.filter
def choice_label(value):
    return CHOICE_LABELS.get(value, value or "—")


@register.simple_tag(takes_context=True)
def can(context, object_key, action):
    from core.policy import allows

    return allows(context["user"], object_key, action)
