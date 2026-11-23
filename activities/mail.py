"""Task and reminder outbound mail (Phase 10C)."""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from activities.models import Reminder, Task
from core.graph_mail import absolute_crm_url, graph_mail_configured, send_crm_mail
from core.services import record_audit
from identity.models import User

logger = logging.getLogger(__name__)


def _task_deep_link() -> str:
    return absolute_crm_url(reverse("activities:tasks"))


def email_task(
    *,
    actor,
    task: Task,
    watcher_ids: list | None = None,
    request_id: str = "",
) -> int:
    """Email the task owner and optional watcher users with a CRM deep link."""
    if not graph_mail_configured():
        raise ValidationError(
            "Outbound CRM email is off until the Microsoft shared mailbox "
            "is configured."
        )
    watchers = []
    if watcher_ids:
        watchers = list(
            User.objects.filter(pk__in=watcher_ids, is_active=True).exclude(
                pk=task.owner_id
            )
        )
    recipients = []
    if task.owner.email:
        recipients.append(task.owner.email)
    for watcher in watchers:
        if watcher.email:
            recipients.append(watcher.email)
    if not recipients:
        raise ValidationError(
            "No recipient email addresses are available for this task."
        )
    due = timezone.localtime(task.due_at).strftime("%m-%d-%Y, %I:%M %p")
    link = _task_deep_link()
    watcher_names = ", ".join(w.display_name for w in watchers) or "none"
    body = (
        f"{actor.display_name} shared a GlideCRM task with you.\n\n"
        f"Title: {task.title}\n"
        f"Owner: {task.owner.display_name}\n"
        f"Due: {due}\n"
        f"Watchers: {watcher_names}\n"
    )
    if task.description:
        body += f"\nNotes:\n{task.description}\n"
    body += f"\nOpen tasks in GlideCRM:\n{link}\n"
    send_crm_mail(
        to_addresses=recipients,
        subject=f"GlideCRM task: {task.title}",
        body_text=body,
        request_id=request_id,
    )
    record_audit(
        actor=actor,
        action="task.emailed",
        instance=task,
        before=None,
        after={
            "recipient_count": len(set(a.lower() for a in recipients)),
            "watcher_count": len(watchers),
        },
        request_id=request_id,
    )
    return len(set(a.lower() for a in recipients))


def send_reminder_email(reminder: Reminder, *, request_id: str = "") -> bool:
    """Send at most one due/overdue email for an in-app reminder row."""
    if not graph_mail_configured():
        return False
    if reminder.email_sent_at is not None:
        return False
    task = reminder.task
    recipient = reminder.recipient
    if not recipient.email:
        logger.info(
            "Reminder email skipped; recipient has no email",
            extra={"outcome": "skipped", "user_id": recipient.pk},
        )
        reminder.email_sent_at = timezone.now()
        reminder.save(update_fields=("email_sent_at",))
        return False
    due = timezone.localtime(task.due_at).strftime("%m-%d-%Y, %I:%M %p")
    link = _task_deep_link()
    body = (
        f"A GlideCRM task is due.\n\n"
        f"Title: {task.title}\n"
        f"Due: {due}\n"
        f"\nOpen tasks in GlideCRM:\n{link}\n"
    )
    send_crm_mail(
        to_addresses=[recipient.email],
        subject=f"GlideCRM reminder: {task.title}",
        body_text=body,
        request_id=request_id,
    )
    reminder.email_sent_at = timezone.now()
    reminder.save(update_fields=("email_sent_at",))
    return True
