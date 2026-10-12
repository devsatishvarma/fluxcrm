"""Task center and quick logging from a lead or deal."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from activities.models import Task
from activities.services import complete_task, create_activity, create_task, snooze_task
from core.access import activate_viewer_timezone, scoped
from core.exceptions import VersionConflict
from leads.models import Lead
from sales.models import Deal

BUCKETS = ("overdue", "due", "upcoming")


def _request_id(request):
    return getattr(request, "request_id", "")


def _bounds(user):
    activate_viewer_timezone(user)
    zone = ZoneInfo(user.timezone or "America/Los_Angeles")
    local_now = timezone.now().astimezone(zone)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_now, start, start + timedelta(days=1)


@login_required
def task_list(request):
    local_now, start, end = _bounds(request.user)
    bucket = request.GET.get("bucket") or "due"
    if bucket not in BUCKETS:
        bucket = "due"
    queryset = scoped(Task.objects.select_related("owner"), request.user).filter(
        status=Task.Status.OPEN
    )
    queryset = queryset.annotate(effective_due=Coalesce("snooze_until", "due_at"))
    if bucket == "overdue":
        queryset = queryset.filter(effective_due__lt=local_now)
    elif bucket == "upcoming":
        queryset = queryset.filter(effective_due__gte=end)
    else:
        queryset = queryset.filter(effective_due__gte=start, effective_due__lt=end)
    return render(
        request,
        "activities/task_list.html",
        {
            "tasks": queryset,
            "bucket": bucket,
            "buckets": BUCKETS,
            "leads": scoped(
                Lead.objects.order_by("company_name", "last_name"),
                request.user,
            ),
            "deals": scoped(Deal.objects.order_by("title"), request.user),
        },
    )


@login_required
@require_POST
def activity_create(request):
    return _create(request, create_activity)


@login_required
@require_POST
def task_create(request):
    return _create(request, create_task)


def _posted_links(post):
    links = []
    seen = set()

    def add(kind, object_id):
        if not kind or not object_id:
            return
        key = (kind, str(object_id))
        if key in seen:
            return
        seen.add(key)
        links.append({"kind": kind, "id": object_id})

    add(post.get("kind"), post.get("object_id"))
    add("lead", post.get("lead_id"))
    add("deal", post.get("deal_id"))
    return links


def _create(request, operation):
    activate_viewer_timezone(request.user)
    kind = request.POST.get("kind")
    object_id = request.POST.get("object_id")
    try:
        operation(
            actor=request.user,
            data=request.POST,
            links=_posted_links(request.POST),
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except ValidationError as exc:
        detail = (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"detail": exc.messages}
        )
        return render(
            request,
            "activities/quick_error.html",
            {"errors": detail, "kind": kind, "object_id": object_id},
            status=422,
        )
    if kind == "deal":
        return redirect("sales:detail", object_id)
    if kind == "lead":
        return redirect("leads:detail", object_id)
    deal_id = request.POST.get("deal_id")
    lead_id = request.POST.get("lead_id")
    if deal_id and not lead_id:
        return redirect("sales:detail", deal_id)
    if lead_id:
        return redirect("leads:detail", lead_id)
    return redirect("activities:tasks")


@login_required
@require_POST
def task_complete(request, task_id):
    return _mutate(request, complete_task, task_id)


@login_required
@require_POST
def task_snooze(request, task_id):
    return _mutate(
        request, snooze_task, task_id, until=request.POST.get("snooze_until")
    )


def _mutate(request, operation, task_id, **extra):
    try:
        operation(
            actor=request.user,
            task_id=task_id,
            version=request.POST.get("version"),
            request_id=_request_id(request),
            **extra,
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except VersionConflict:
        return render(
            request,
            "activities/quick_error.html",
            {"errors": {"version": ["This record changed. Reload and try again."]}},
            status=409,
        )
    except ValidationError as exc:
        detail = (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"detail": exc.messages}
        )
        return render(
            request, "activities/quick_error.html", {"errors": detail}, status=422
        )
    return redirect("activities:tasks")
