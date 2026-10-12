"""Activity and task operations shared by the HTML pages and API."""

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import Account, Contact
from activities.models import Activity, ActivityLink, Task, TaskLink
from audit.models import AuditEvent
from core.access import get_scoped
from core.exceptions import VersionConflict
from core.validation import clean_external_id, clean_owner, require_version
from identity.models import CompanySettings
from leads.models import Lead
from sales.models import Deal

logger = logging.getLogger(__name__)
LINKABLE = {"lead": Lead, "deal": Deal, "account": Account, "contact": Contact}


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
    activities = Activity.objects.filter(
        links__content_type=content_type,
        links__object_id=record.pk,
    ).select_related("owner")
    tasks = Task.objects.filter(
        links__content_type=content_type,
        links__object_id=record.pk,
    ).select_related("owner")
    return activities.distinct(), tasks.distinct()


def _links(actor, raw_links):
    if not raw_links:
        raise ValidationError({"links": "Link the record to a lead or deal."})
    resolved = []
    seen = set()
    for item in raw_links:
        kind = str(item.get("kind") or "").strip()
        model = LINKABLE.get(kind)
        if model is None:
            raise ValidationError({"links": "Link a lead or a deal."})
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
        owner=clean_owner(actor, data.get("owner")),
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
        owner=clean_owner(actor, data.get("owner")),
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
    task = get_scoped(Task, actor, task_id, for_update=True)
    if require_version(version) != task.version:
        raise VersionConflict
    return task


@transaction.atomic
def complete_task(*, actor, task_id, version, request_id=""):
    task = _locked_task(actor, task_id, version)
    if task.status != Task.Status.OPEN:
        raise ValidationError({"status": "Only an open task can be completed."})
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
