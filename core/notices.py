"""Short success and failure notices for button actions."""

from django.contrib import messages

from core.taxonomy import TAXONOMY


def succeeded(request, text):
    messages.success(request, text)


def warned(request, text):
    messages.warning(request, text)


def failed(request, text):
    messages.error(request, text)


def fail_with(request, prefix, detail):
    detail = str(detail or "").strip()
    failed(request, f"{prefix} {detail}".strip())


def validation_text(exc):
    if hasattr(exc, "message_dict"):
        parts = []
        for field, items in exc.message_dict.items():
            for item in items:
                if field in {"__all__", "detail"}:
                    parts.append(str(item))
                else:
                    parts.append(f"{_label(field)}: {item}")
        return _join(parts)
    return _join(getattr(exc, "messages", [str(exc)]))


def form_text(form):
    parts = []
    for field, errors in form.errors.items():
        for error in errors:
            if field == "__all__":
                parts.append(str(error))
            else:
                label = (
                    form.fields[field].label if field in form.fields else _label(field)
                )
                parts.append(f"{label}: {error}")
    return _join(parts)


def payload_text(payload):
    parts = []
    for field, items in payload.items():
        if not isinstance(items, (list, tuple)):
            items = [items]
        for item in items:
            if field in {"detail", "__all__"}:
                parts.append(str(item))
            else:
                parts.append(f"{_label(field)}: {item}")
    return _join(parts)


def stage_name(list_key, key):
    for item, label in TAXONOMY.get(list_key, ()):
        if item == key:
            return label
    text = str(key or "").replace("_", " ").strip()
    return text or "the selected stage"


def _label(field):
    text = str(field).replace("_", " ")
    return text[:1].upper() + text[1:] if text else text


def _join(parts):
    return " ".join(str(part).strip() for part in parts if str(part).strip())
