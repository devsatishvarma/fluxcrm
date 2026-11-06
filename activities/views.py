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
    update_task,
)
from core.access import activate_viewer_timezone, scoped
from core.exceptions import VersionConflict
from core.notices import fail_with, failed, succeeded, validation_text
from core.policy import require_action
from core.validation import require_delete_confirmation
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
    activate_viewer_timezone(request.user)
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
    return _create(
        request,
        create_activity,
        success="Activity {name} added.",
        failure="Could not add the activity.",
    )


@login_required
@require_POST
def task_create(request):
    return _create(
        request,
        create_task,
        success="Task {name} added.",
        failure="Could not add the task.",
    )


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


def _create(request, operation, *, success, failure):
    activate_viewer_timezone(request.user)
    kind = request.POST.get("kind")
    object_id = request.POST.get("object_id")
    try:
        record = operation(
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
        fail_with(request, failure, validation_text(exc))
        return render(
            request,
            "activities/quick_error.html",
            {"errors": detail, "kind": kind, "object_id": object_id},
            status=422,
        )
    name = getattr(record, "subject", None) or getattr(record, "title", "")
    succeeded(request, success.format(name=name))
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
    return _mutate(
        request,
        complete_task,
        task_id,
        success="Task {name} completed.",
        failure="Could not complete the task.",
        completion_notes=request.POST.get("completion_notes", ""),
    )


@login_required
@require_POST
def task_cancel(request, task_id):
    return _mutate(
        request,
        change_task_status,
        task_id,
        success="Task {name} cancelled.",
        failure="Could not cancel the task.",
        status=Task.Status.CANCELLED,
    )


@login_required
@require_POST
def task_hold(request, task_id):
    return _mutate(
        request,
        change_task_status,
        task_id,
        success="Task {name} put on hold.",
        failure="Could not hold the task.",
        status=Task.Status.HOLD,
    )


@login_required
@require_POST
def task_resume(request, task_id):
    return _mutate(
        request,
        change_task_status,
        task_id,
        success="Task {name} resumed.",
        failure="Could not resume the task.",
        status=Task.Status.OPEN,
    )


@login_required
@require_POST
def task_delete(request, task_id):
    try:
        require_action(request.user, "task", "D", object_id=task_id)
        require_delete_confirmation(request.POST)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except ValidationError as exc:
        fail_with(request, "Could not delete the task.", validation_text(exc))
        return render(
            request,
            "activities/quick_error.html",
            {"errors": {"detail": exc.messages}},
            status=422,
        )
    return _mutate(
        request,
        delete_task,
        task_id,
        success="Task {name} deleted.",
        failure="Could not delete the task.",
        delete_reason=request.POST.get("delete_reason"),
    )


@login_required
@require_POST
def task_update(request, task_id):
    try:
        task = update_task(
            actor=request.user,
            task_id=task_id,
            version=request.POST.get("version"),
            data=request.POST,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except VersionConflict:
        failed(
            request,
            "Could not save the task. This record changed. Reload and try again.",
        )
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
        fail_with(request, "Could not save the task.", validation_text(exc))
        return render(
            request, "activities/quick_error.html", {"errors": detail}, status=422
        )
    succeeded(request, f"Task {task.title} saved.")
    return _back(request)


@login_required
@require_POST
def activity_update(request, activity_id):
    try:
        activity = update_activity(
            actor=request.user,
            activity_id=activity_id,
            version=request.POST.get("version"),
            data=request.POST,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except VersionConflict:
        failed(
            request,
            "Could not save the activity. This record changed. Reload and try again.",
        )
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
        fail_with(request, "Could not save the activity.", validation_text(exc))
        return render(
            request, "activities/quick_error.html", {"errors": detail}, status=422
        )
    succeeded(request, f"Activity {activity.subject} saved.")
    return _back(request)


@login_required
@require_POST
def activity_delete(request, activity_id):
    try:
        require_action(request.user, "activity", "D", object_id=activity_id)
        require_delete_confirmation(request.POST)
        activity = delete_activity(
            actor=request.user,
            activity_id=activity_id,
            version=request.POST.get("version"),
            delete_reason=request.POST.get("delete_reason"),
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except VersionConflict:
        failed(
            request,
            "Could not delete the activity. This record changed. Reload and try again.",
        )
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
        fail_with(request, "Could not delete the activity.", validation_text(exc))
        return render(
            request, "activities/quick_error.html", {"errors": detail}, status=422
        )
    succeeded(request, f"Activity {activity.subject} deleted.")
    return _back(request)


@login_required
@require_POST
def task_snooze(request, task_id):
    return _mutate(
        request,
        snooze_task,
        task_id,
        success="Task {name} snoozed.",
        failure="Could not snooze the task.",
        until=request.POST.get("snooze_until"),
    )


def _mutate(request, operation, task_id, *, success, failure, **extra):
    try:
        task = operation(
            actor=request.user,
            task_id=task_id,
            version=request.POST.get("version"),
            request_id=_request_id(request),
            **extra,
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except VersionConflict:
        failed(request, f"{failure} This record changed. Reload and try again.")
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
        fail_with(request, failure, validation_text(exc))
        return render(
            request, "activities/quick_error.html", {"errors": detail}, status=422
        )
    succeeded(request, success.format(name=task.title))
    return _back(request)
