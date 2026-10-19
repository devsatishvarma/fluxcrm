"""Activity and task operations shared by the HTML pages and API."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import Account, Contact
from activities.models import Activity, ActivityLink, Task, TaskLink
from audit.models import AuditEvent
from core.access import activate_viewer_timezone, get_scoped, scoped
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
LOGGED_ACTIVITY_TYPES = (
    Activity.Type.CALL,
    Activity.Type.EMAIL,
    Activity.Type.MEETING,
    Activity.Type.NOTE,
)
NOTE_LIMIT = 4000
PARTY_MESSAGE = (
    "Choose a contact or lead. Create that person first if they are not listed."
)
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
        .select_related("owner", "with_contact", "with_contact__account", "with_lead")
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
            "with_whom": instance.with_whom,
            "with_contact_id": (
                None
                if instance.with_contact_id is None
                else str(instance.with_contact_id)
            ),
            "with_lead_id": (
                None if instance.with_lead_id is None else str(instance.with_lead_id)
            ),
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


def _logged_type(value):
    activity_type = str(value or "").strip()
    if activity_type not in LOGGED_ACTIVITY_TYPES:
        raise ValidationError(
            {"activity_type": "Choose a call, email, meeting, or note."}
        )
    return activity_type


def activity_parties(user):
    """Contacts and leads this person can assign to an activity."""
    from accounts.services import contacts_for_user

    contacts = []
    for contact in contacts_for_user(user).order_by(
        "last_name", "first_name", "account__name"
    ):
        name = f"{contact.first_name} {contact.last_name}".strip()
        contacts.append(
            {
                "value": f"contact:{contact.pk}",
                "label": name,
                "search": f"{name} {contact.account.name}".casefold(),
            }
        )
    leads = []
    for lead in scoped(Lead.objects.all(), user).order_by(
        "last_name", "first_name", "company_name"
    ):
        name = f"{lead.first_name} {lead.last_name}".strip()
        leads.append(
            {
                "value": f"lead:{lead.pk}",
                "label": name,
                "search": f"{name} {lead.company_name}".casefold(),
            }
        )
    return {"contacts": contacts, "leads": leads}


def suggested_party(user, kind, object_id):
    """Prefer the person already open on this page."""
    if not object_id:
        return ""
    if kind == "lead" and scoped(Lead.objects.filter(pk=object_id), user).exists():
        return f"lead:{object_id}"
    if kind == "account":
        from accounts.services import contacts_for_user

        contact = (
            contacts_for_user(user)
            .filter(account_id=object_id, is_primary=True)
            .order_by("last_name", "first_name")
            .first()
        )
        if contact is not None:
            return f"contact:{contact.pk}"
    if kind == "deal":
        deal = (
            scoped(Deal.objects.select_related("primary_contact"), user)
            .filter(pk=object_id)
            .first()
        )
        if deal is None:
            return ""
        if deal.primary_contact_id:
            from accounts.services import contacts_for_user

            if contacts_for_user(user).filter(pk=deal.primary_contact_id).exists():
                return f"contact:{deal.primary_contact_id}"
        if deal.lead_id and scoped(Lead.objects.filter(pk=deal.lead_id), user).exists():
            return f"lead:{deal.lead_id}"
    return ""


def _visible_party(model, actor, object_id):
    try:
        return get_scoped(model, actor, object_id)
    except PermissionDenied:
        raise
    except (Http404, ValidationError, ValueError):
        raise ValidationError({"with_party": PARTY_MESSAGE}) from None


def _party(actor, data, *, required):
    raw = str(data.get("with_party") or "").strip()
    contact_id = str(data.get("with_contact") or "").strip()
    lead_id = str(data.get("with_lead") or "").strip()
    if raw:
        kind, separator, value = raw.partition(":")
        if separator and kind == "contact" and value:
            contact_id, lead_id = value, ""
        elif separator and kind == "lead" and value:
            lead_id, contact_id = value, ""
        else:
            raise ValidationError({"with_party": PARTY_MESSAGE})
    if contact_id and lead_id:
        raise ValidationError({"with_party": "Choose one contact or one lead."})
    if not contact_id and not lead_id:
        if required:
            raise ValidationError({"with_party": PARTY_MESSAGE})
        return None, None, ""
    if contact_id:
        contact = _visible_party(Contact, actor, contact_id)
        name = f"{contact.first_name} {contact.last_name}".strip()
        return contact, None, name[:200]
    lead = _visible_party(Lead, actor, lead_id)
    name = f"{lead.first_name} {lead.last_name}".strip()
    return None, lead, name[:200]


def _notes(value, field):
    text = str(value or "").strip()
    if len(text) > NOTE_LIMIT:
        raise ValidationError({field: "Notes must be 4000 characters or fewer."})
    return text


@transaction.atomic
def create_activity(*, actor, data, links, request_id="", logged=True):
    from core.policy import require_action

    require_action(actor, "activity", "C")
    if logged:
        activity_type = _logged_type(data.get("activity_type"))
    else:
        activity_type = str(data.get("activity_type") or "").strip()
        if activity_type not in Activity.Type.values:
            raise ValidationError(
                {"activity_type": "Choose a call, email, meeting, or note."}
            )
    subject = str(data.get("subject") or "").strip()
    if not subject:
        raise ValidationError({"subject": "This field is required."})
    occurred_at = user_datetime(data.get("occurred_at"), actor, "occurred_at")
    if occurred_at is None:
        if logged:
            raise ValidationError({"occurred_at": "Enter when this activity happened."})
        occurred_at = timezone.now()
    contact, lead, party_name = _party(actor, data, required=logged)
    resolved = _links(actor, links)
    activity = Activity(
        external_id=clean_external_id(data.get("external_id")),
        activity_type=activity_type,
        subject=subject[:200],
        with_whom=party_name,
        with_contact=contact,
        with_lead=lead,
        body=_notes(data.get("body"), "body"),
        occurred_at=occurred_at,
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
        description=_notes(data.get("description"), "description"),
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


@transaction.atomic
def update_task(*, actor, task_id, version, data, request_id=""):
    task = _locked_task(actor, task_id, version)
    if task.status not in {Task.Status.OPEN, Task.Status.HOLD}:
        raise ValidationError({"status": "Only an open or held task can be edited."})
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValidationError({"title": "This field is required."})
    due_at = user_datetime(data.get("due_at"), actor, "due_at")
    if due_at is None:
        raise ValidationError({"due_at": "Enter a due time."})
    priority = str(data.get("priority") or task.priority)
    if priority not in Task.Priority.values:
        raise ValidationError({"priority": "Choose a valid priority."})
    before = _snapshot(task)
    task.title = title[:200]
    if "description" in data:
        task.description = _notes(data.get("description"), "description")
    task.due_at = due_at
    task.priority = priority
    task.updated_by = actor
    task.version += 1
    task.full_clean()
    task.save()
    _audit(actor, "task.updated", task, before, request_id)
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
    activity_type = _logged_type(data.get("activity_type") or activity.activity_type)
    subject = str(data.get("subject") or "").strip()
    if not subject:
        raise ValidationError({"subject": "This field is required."})
    before = _snapshot(activity)
    activity.activity_type = activity_type
    activity.subject = subject[:200]
    if any(key in data for key in ("with_party", "with_contact", "with_lead")):
        contact, lead, party_name = _party(actor, data, required=True)
        activity.with_contact = contact
        activity.with_lead = lead
        activity.with_whom = party_name
    if "body" in data:
        activity.body = _notes(data.get("body"), "body")
    activity.outcome = str(
        data.get("outcome") if "outcome" in data else activity.outcome
    ).strip()[:200]
    if "occurred_at" in data:
        occurred_at = user_datetime(data.get("occurred_at"), actor, "occurred_at")
        if occurred_at is None:
            raise ValidationError({"occurred_at": "Enter when this activity happened."})
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
