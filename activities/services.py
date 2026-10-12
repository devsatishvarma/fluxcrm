"""Activity and task operations shared by the HTML pages and API."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import Account, Contact
from activities.models import Activity, ActivityLink, Task, TaskLink
from audit.models import AuditEvent
from core.access import activate_viewer_timezone, get_scoped
from core.exceptions import VersionConflict
from core.policy import require_action
from core.validation import (
    clean_delete_reason,
    clean_external_id,
    clean_owner,
    require_version,
)
from identity.models import CompanySettings
from leads.models import Lead
from sales.models import Deal

logger = logging.getLogger(__name__)
LINKABLE = {"lead": Lead, "deal": Deal, "account": Account, "contact": Contact}
TASK_BUCKETS = (
    ("open", "Open"),
    ("overdue", "Overdue"),
    ("due", "Due today"),
    ("upcoming", "Upcoming"),
    ("held", "On hold"),
    ("done", "Completed"),
    ("cancelled", "Cancelled"),
)
TASK_BUCKET_KEYS = {key for key, _label in TASK_BUCKETS}


def local_day_bounds(user):
    activate_viewer_timezone(user)
    zone = ZoneInfo(getattr(user, "timezone", "") or "America/Los_Angeles")
    local_now = timezone.now().astimezone(zone)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_now, start, start + timedelta(days=1)


def filter_task_bucket(queryset, bucket, user):
    """Limit a task list to one task-center view.

    Open is every open task. Overdue means the due time has passed. Due today
    means it is still due later today. Upcoming means it is due after today.
    """
    if bucket not in TASK_BUCKET_KEYS:
        bucket = "open"
    queryset = queryset.annotate(effective_due=Coalesce("snooze_until", "due_at"))
    if bucket == "held":
        return queryset.filter(status=Task.Status.HOLD)
    if bucket == "done":
        return queryset.filter(status=Task.Status.DONE)
    if bucket == "cancelled":
        return queryset.filter(status=Task.Status.CANCELLED)
    queryset = queryset.filter(status=Task.Status.OPEN)
    if bucket == "open":
        return queryset
    local_now, _start, end = local_day_bounds(user)
    if bucket == "overdue":
        return queryset.filter(effective_due__lt=local_now)
    if bucket == "upcoming":
        return queryset.filter(effective_due__gte=end)
    return queryset.filter(effective_due__gte=local_now, effective_due__lt=end)


def _zone(user):
    try:
        return ZoneInfo(getattr(user, "timezone", "") or "America/Los_Angeles")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Los_Angeles")


def user_datetime(value, user, field):
    """Interpret a naive wall time in the user's zone and keep offsets as given."""
    if value in (None, ""):
        return None
    if hasattr(value, "tzinfo"):
        if timezone.is_naive(value):
            return timezone.make_aware(value, _zone(user))
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError({field: "Enter a valid date and time."})
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, _zone(user))
    return parsed


def stale_days(kind):
    company = CompanySettings.objects.first()
    if company is None:
        return 14 if kind == "lead" else 21
    return company.lead_stale_days if kind == "lead" else company.deal_stale_days


def attach_freshness(records, kind):
    """Mark the current page stale with one grouped activity query."""
    if not records:
        return
    content_type = ContentType.objects.get_for_model(records[0].__class__)
    latest = {
        row["object_id"]: row["last_at"]
        for row in ActivityLink.objects.filter(
            content_type=content_type,
            object_id__in=[record.pk for record in records],
            activity__deleted_at__isnull=True,
        )
        .values("object_id")
        .annotate(last_at=Max("activity__occurred_at"))
    }
    cutoff = timezone.now() - timedelta(days=stale_days(kind))
    for record in records:
        last_at = latest.get(record.pk) or record.created_at
        record.is_stale = last_at < cutoff
        record.last_activity_at = latest.get(record.pk)


def timeline(record):
    content_type = ContentType.objects.get_for_model(record.__class__)
    activities = list(
        Activity.objects.filter(
            links__content_type=content_type,
            links__object_id=record.pk,
        )
        .select_related("owner")
        .distinct()
    )
    tasks = list(
        Task.objects.filter(
            links__content_type=content_type,
            links__object_id=record.pk,
        )
        .select_related("owner")
        .distinct()
    )
    attach_related(tasks)
    return activities, tasks


def attach_related(tasks):
    """Name the lead, contact, and deal linked to each task."""
    from django.urls import reverse

    task_list = list(tasks)
    if not task_list:
        return task_list
    links = TaskLink.objects.filter(task__in=task_list).select_related("content_type")
    grouped = {}
    for link in links:
        grouped.setdefault(link.content_type_id, []).append(link.object_id)
    found = {}
    for content_type_id, object_ids in grouped.items():
        model = ContentType.objects.get_for_id(content_type_id).model_class()
        for record in model.objects.filter(pk__in=object_ids):
            found[(content_type_id, record.pk)] = record
    by_task = {task.pk: [] for task in task_list}
    for link in links:
        record = found.get((link.content_type_id, link.object_id))
        if record is None:
            continue
        kind = link.content_type.model
        label, url = _related_label(kind, record, reverse)
        by_task[link.task_id].append({"kind": kind, "label": label, "url": url})
    for task in task_list:
        task.related = by_task.get(task.pk, [])
    return task_list


def _related_label(kind, record, reverse):
    if kind == "lead":
        name = f"{record.first_name} {record.last_name}".strip()
        return name, reverse("leads:detail", args=[record.pk])
    if kind == "contact":
        name = f"{record.first_name} {record.last_name}".strip()
        return name, reverse("accounts:detail", args=[record.account_id])
    if kind == "deal":
        return record.title, reverse("sales:detail", args=[record.pk])
    if kind == "account":
        return record.name, reverse("accounts:detail", args=[record.pk])
    return str(record), ""


def _links(actor, raw_links):
    if not raw_links:
        raise ValidationError({"links": "Link the record to a lead or deal."})
    resolved = []
    seen = set()
    for item in raw_links:
        kind = str(item.get("kind") or "").strip()
        model = LINKABLE.get(kind)
        if model is None:
            raise ValidationError({"links": "Link a lead, contact, account, or deal."})
        try:
            record = get_scoped(model, actor, item.get("id"))
        except PermissionDenied:
            raise
        key = (kind, record.pk)
        if key in seen:
            continue
        seen.add(key)
        resolved.append((ContentType.objects.get_for_model(model), record))
    return resolved


def _audit(actor, action, instance, before, request_id):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        before_json=before,
        after_json=_snapshot(instance),
        request_id=request_id,
        source="web",
    )
    logger.info(action, extra={"object_id": str(instance.pk), "outcome": "success"})


def _snapshot(instance):
    if isinstance(instance, Activity):
        return {
            "external_id": instance.external_id,
            "activity_type": instance.activity_type,
            "subject": instance.subject,
            "occurred_at": instance.occurred_at.isoformat(),
            "owner_id": instance.owner_id,
            "version": instance.version,
        }
    return {
        "external_id": instance.external_id,
        "title": instance.title,
        "due_at": instance.due_at.isoformat(),
        "status": instance.status,
        "owner_id": instance.owner_id,
        "snooze_until": (
            None if instance.snooze_until is None else instance.snooze_until.isoformat()
        ),
        "version": instance.version,
    }


@transaction.atomic
def create_activity(*, actor, data, links, request_id=""):
    from core.policy import require_action

    require_action(actor, "activity", "C")
    activity_type = str(data.get("activity_type") or "").strip()
    if activity_type not in Activity.Type.values:
        raise ValidationError(
            {"activity_type": "Choose a call, email, meeting, or note."}
        )
    subject = str(data.get("subject") or "").strip()
    if not subject:
        raise ValidationError({"subject": "This field is required."})
    resolved = _links(actor, links)
    activity = Activity(
        external_id=clean_external_id(data.get("external_id")),
        activity_type=activity_type,
        subject=subject[:200],
        body=str(data.get("body") or "").strip(),
        occurred_at=user_datetime(data.get("occurred_at"), actor, "occurred_at")
        or timezone.now(),
        outcome=str(data.get("outcome") or "").strip()[:200],
        owner=clean_owner(actor, data.get("owner"), object_key="activity"),
        created_by=actor,
        updated_by=actor,
        source="MANUAL",
    )
    activity.full_clean()
    activity.save()
    ActivityLink.objects.bulk_create(
        [
            ActivityLink(
                activity=activity, content_type=content_type, object_id=record.pk
            )
            for content_type, record in resolved
        ]
    )
    _audit(actor, "activity.created", activity, None, request_id)
    return activity


@transaction.atomic
def create_task(*, actor, data, links, request_id=""):
    from core.policy import require_action

    require_action(actor, "task", "C")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValidationError({"title": "This field is required."})
    due_at = user_datetime(data.get("due_at"), actor, "due_at")
    if due_at is None:
        raise ValidationError({"due_at": "Enter a due time."})
    priority = str(data.get("priority") or Task.Priority.NORMAL)
    if priority not in Task.Priority.values:
        raise ValidationError({"priority": "Choose a valid priority."})
    resolved = _links(actor, links)
    task = Task(
        external_id=clean_external_id(data.get("external_id")),
        title=title[:200],
        description=str(data.get("description") or "").strip(),
        due_at=due_at,
        priority=priority,
        owner=clean_owner(actor, data.get("owner"), object_key="task"),
        created_by=actor,
        updated_by=actor,
    )
    task.full_clean()
    task.save()
    TaskLink.objects.bulk_create(
        [
            TaskLink(task=task, content_type=content_type, object_id=record.pk)
            for content_type, record in resolved
        ]
    )
    _audit(actor, "task.created", task, None, request_id)
    return task


def _locked_task(actor, task_id, version):
    require_action(actor, "task", "U", object_id=task_id)
    task = get_scoped(Task, actor, task_id, for_update=True)
    if require_version(version) != task.version:
        raise VersionConflict
    return task


@transaction.atomic
def complete_task(*, actor, task_id, version, request_id=""):
    task = _locked_task(actor, task_id, version)
    if task.status not in {Task.Status.OPEN, Task.Status.HOLD}:
        raise ValidationError({"status": "Only an open or held task can be completed."})
    before = _snapshot(task)
    task.status = Task.Status.DONE
    task.completed_at = timezone.now()
    task.updated_by = actor
    task.version += 1
    task.save()
    _audit(actor, "task.completed", task, before, request_id)
    return task


@transaction.atomic
def snooze_task(*, actor, task_id, version, until, request_id=""):
    task = _locked_task(actor, task_id, version)
    if task.status != Task.Status.OPEN:
        raise ValidationError({"status": "Only an open task can be snoozed."})
    snooze_until = user_datetime(until, actor, "snooze_until")
    if snooze_until is None or snooze_until <= timezone.now():
        raise ValidationError({"snooze_until": "Choose a future snooze time."})
    before = _snapshot(task)
    task.snooze_until = snooze_until
    task.reminder_sent_at = None
    task.updated_by = actor
    task.version += 1
    task.save()
    _audit(actor, "task.snoozed", task, before, request_id)
    return task


_STATUS_FROM = {
    Task.Status.HOLD: {Task.Status.OPEN},
    Task.Status.OPEN: {Task.Status.HOLD},
    Task.Status.CANCELLED: {Task.Status.OPEN, Task.Status.HOLD},
}


@transaction.atomic
def change_task_status(*, actor, task_id, version, status, request_id=""):
    """Cancel, hold, or resume a task. Delete is a separate soft delete."""
    task = _locked_task(actor, task_id, version)
    destination = str(status or "").strip()
    allowed = _STATUS_FROM.get(destination)
    if allowed is None or task.status not in allowed:
        raise ValidationError({"status": "That task status change is not allowed."})
    before = _snapshot(task)
    task.status = destination
    if destination != Task.Status.OPEN:
        task.snooze_until = None
    task.updated_by = actor
    task.version += 1
    task.save()
    _audit(actor, "task.status_changed", task, before, request_id)
    return task


@transaction.atomic
def delete_task(*, actor, task_id, version, delete_reason, request_id=""):
    require_action(actor, "task", "D", object_id=task_id)
    task = get_scoped(Task, actor, task_id, for_update=True)
    if require_version(version) != task.version:
        raise VersionConflict
    before = _snapshot(task)
    task.deleted_at = datetime.now(UTC)
    task.deleted_by = actor
    task.delete_reason = clean_delete_reason(delete_reason)
    task.updated_by = actor
    task.version += 1
    task.save()
    _audit(actor, "task.deleted", task, before, request_id)
    return task


def _locked_activity(actor, activity_id, version):
    require_action(actor, "activity", "U", object_id=activity_id)
    activity = get_scoped(Activity, actor, activity_id, for_update=True)
    if require_version(version) != activity.version:
        raise VersionConflict
    return activity


@transaction.atomic
def update_activity(*, actor, activity_id, version, data, request_id=""):
    activity = _locked_activity(actor, activity_id, version)
    activity_type = str(data.get("activity_type") or activity.activity_type).strip()
    if activity_type not in Activity.Type.values:
        raise ValidationError(
            {"activity_type": "Choose a call, email, meeting, or note."}
        )
    subject = str(data.get("subject") or "").strip()
    if not subject:
        raise ValidationError({"subject": "This field is required."})
    before = _snapshot(activity)
    activity.activity_type = activity_type
    activity.subject = subject[:200]
    activity.body = str(data.get("body") if "body" in data else activity.body).strip()
    activity.outcome = str(
        data.get("outcome") if "outcome" in data else activity.outcome
    ).strip()[:200]
    occurred_at = user_datetime(data.get("occurred_at"), actor, "occurred_at")
    if occurred_at is not None:
        activity.occurred_at = occurred_at
    activity.updated_by = actor
    activity.version += 1
    activity.full_clean()
    activity.save()
    _audit(actor, "activity.updated", activity, before, request_id)
    return activity


@transaction.atomic
def delete_activity(*, actor, activity_id, version, delete_reason, request_id=""):
    require_action(actor, "activity", "D", object_id=activity_id)
    activity = get_scoped(Activity, actor, activity_id, for_update=True)
    if require_version(version) != activity.version:
        raise VersionConflict
    before = _snapshot(activity)
    activity.deleted_at = datetime.now(UTC)
    activity.deleted_by = actor
    activity.delete_reason = clean_delete_reason(delete_reason)
    activity.updated_by = actor
    activity.version += 1
    activity.save()
    _audit(actor, "activity.deleted", activity, before, request_id)
    return activity
