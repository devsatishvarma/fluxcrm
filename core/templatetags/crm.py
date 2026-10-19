from django import template

from core.display import (
    duration_phrase,
    elapsed_phrase,
    format_address,
    format_money,
    format_phone,
    format_whole,
)

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
def whole(value):
    return format_whole(value)


@register.filter
def address(value):
    return format_address(value)


@register.filter
def phone(value):
    return format_phone(value)


@register.filter
def choice_label(value):
    return CHOICE_LABELS.get(value, value or "—")


@register.filter
def stage_label(value):
    from core.taxonomy import TAXONOMY

    key = str(value or "")
    for list_key in ("LEAD_STAGE", "DEAL_STAGE"):
        for item, label in TAXONOMY.get(list_key, ()):
            if item == key:
                return label
    text = key.replace("_", " ").strip()
    return text or "—"


@register.filter
def lookup(row, key):
    if isinstance(row, dict):
        return row.get(key, "")
    return ""


@register.simple_tag(takes_context=True)
def can(context, object_key, action):
    from core.policy import allows

    return allows(context["user"], object_key, action)


@register.simple_tag
def activity_parties(user):
    from activities.services import activity_parties as choices

    return choices(user)


@register.simple_tag
def suggested_party(user, kind, object_id):
    from activities.services import suggested_party as choice

    return choice(user, kind, object_id)
