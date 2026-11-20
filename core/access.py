"""Record-scope checks. Grants live in core.policy."""

from django.http import Http404

from core.policy import deny, grant_for, object_key_for, owner_ids_for


def activate_viewer_timezone(user):
    """Render CRM dates in the signed-in user's time zone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from django.utils import timezone

    name = getattr(user, "timezone", "") or "America/Los_Angeles"
    try:
        timezone.activate(ZoneInfo(name))
    except ZoneInfoNotFoundError:
        timezone.activate(ZoneInfo("America/Los_Angeles"))


def scoped(queryset, user, owner_field="owner", action="R"):
    """Limit a queryset to the records this user may take this action on."""
    key = object_key_for(queryset.model)
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    grant = grant_for(user, key) if key else None
    if grant is None or action not in grant.actions:
        return queryset.none()
    allowed = owner_ids_for(user, grant.scope_for(action))
    if allowed is None:
        return queryset
    return queryset.filter(**{f"{owner_field}_id__in": allowed})


def get_scoped(
    model, user, object_id, *, for_update=False, related=("owner",), action="R"
):
    """Return one in-scope record, or 403 when it is outside that action."""
    queryset = model.objects.select_related(*related)
    if for_update:
        queryset = queryset.select_for_update(of=("self",))
    try:
        return scoped(queryset, user, action=action).get(pk=object_id)
    except model.DoesNotExist as exc:
        if model.objects.filter(pk=object_id).exists():
            key = object_key_for(model) or model._meta.model_name
            reason = (
                "missing_grant"
                if action not in grant_for(user, key).actions
                else "out_of_scope"
            )
            deny(user, key, action, object_id=object_id, reason=reason)
        raise Http404 from exc
