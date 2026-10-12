"""Task center and quick logging from a lead or deal."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.services import contacts_for_user
from activities.models import Task
from activities.services import (
    TASK_BUCKET_KEYS,
    TASK_BUCKETS,
    attach_related,
    change_task_status,
    complete_task,
    create_activity,
    create_task,
    delete_activity,
    delete_task,
    filter_task_bucket,
    snooze_task,
    update_activity,
)
from core.access import activate_viewer_timezone, scoped
from core.exceptions import VersionConflict
from leads.models import Lead
from sales.models import Deal

TASK_ORDERING = {
    "due": "effective_due",
    "-due": "-effective_due",
    "priority": "priority",
    "-priority": "-priority",
    "owner": "owner__display_name",
    "-owner": "-owner__display_name",
    "title": "title",
    "-title": "-title",
}


def _request_id(request):
    return getattr(request, "request_id", "")


@login_required
def task_list(request):
    bucket = request.GET.get("bucket") or "open"
    if bucket not in TASK_BUCKET_KEYS:
        bucket = "open"
    queryset = scoped(Task.objects.select_related("owner"), request.user)
    queryset = filter_task_bucket(queryset, bucket, request.user)
    ordering = request.GET.get("ordering") or "due"
    if ordering not in TASK_ORDERING:
        ordering = "due"
    tasks = attach_related(queryset.order_by(TASK_ORDERING[ordering], "pk"))
    return render(
        request,
        "activities/task_list.html",
        {
            "tasks": tasks,
            "bucket": bucket,
            "buckets": TASK_BUCKETS,
            "ordering": ordering,
            "leads": scoped(
                Lead.objects.order_by("company_name", "last_name"),
                request.user,
            ),
            "deals": scoped(Deal.objects.order_by("title"), request.user),
            "contacts": contacts_for_user(request.user).order_by(
                "last_name", "first_name"
            ),
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
    add("contact", post.get("contact_id"))
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
    return _back(request)


def _back(request):
    kind = request.POST.get("kind")
    object_id = request.POST.get("object_id")
    if kind == "lead" and object_id:
        return redirect("leads:detail", object_id)
    if kind == "deal" and object_id:
        return redirect("sales:detail", object_id)
    if kind == "account" and object_id:
        return redirect("accounts:detail", object_id)
    if kind == "contact" and object_id:
        return redirect("accounts:contacts")
    return redirect("activities:tasks")


@login_required
@require_POST
def task_complete(request, task_id):
    return _mutate(request, complete_task, task_id)


@login_required
@require_POST
def task_cancel(request, task_id):
    return _mutate(request, change_task_status, task_id, status=Task.Status.CANCELLED)


@login_required
@require_POST
def task_hold(request, task_id):
    return _mutate(request, change_task_status, task_id, status=Task.Status.HOLD)


@login_required
@require_POST
def task_resume(request, task_id):
    return _mutate(request, change_task_status, task_id, status=Task.Status.OPEN)


@login_required
@require_POST
def task_delete(request, task_id):
    return _mutate(
        request,
        delete_task,
        task_id,
        delete_reason=request.POST.get("delete_reason"),
    )


@login_required
@require_POST
def activity_update(request, activity_id):
    try:
        update_activity(
            actor=request.user,
            activity_id=activity_id,
            version=request.POST.get("version"),
            data=request.POST,
            request_id=_request_id(request),
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
    return _back(request)


@login_required
@require_POST
def activity_delete(request, activity_id):
    try:
        delete_activity(
            actor=request.user,
            activity_id=activity_id,
            version=request.POST.get("version"),
            delete_reason=request.POST.get("delete_reason"),
            request_id=_request_id(request),
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
    return _back(request)


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
    return _back(request)
