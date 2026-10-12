"""Owner-scope checks for CRM records."""

from django.core.exceptions import PermissionDenied
from django.http import Http404


def activate_viewer_timezone(user):
    """Render CRM dates in the signed-in user's time zone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from django.utils import timezone

    name = getattr(user, "timezone", "") or "America/Los_Angeles"
    try:
        timezone.activate(ZoneInfo(name))
    except ZoneInfoNotFoundError:
        timezone.activate(ZoneInfo("America/Los_Angeles"))


def scoped(queryset, user, owner_field="owner"):
    """Limit a queryset to the records this user may read."""
    if getattr(user, "is_company_admin", False):
        return queryset
    return queryset.filter(**{f"{owner_field}_id": user.pk})


def get_scoped(model, user, object_id, *, for_update=False, related=("owner",)):
    """Return one visible record, or 403 when it belongs to someone else."""
    queryset = model.objects.select_related(*related)
    if for_update:
        queryset = queryset.select_for_update(of=("self",))
    try:
        return scoped(queryset, user).get(pk=object_id)
    except model.DoesNotExist as exc:
        if model.objects.filter(pk=object_id).exists():
            raise PermissionDenied from exc
        raise Http404 from exc
