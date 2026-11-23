"""Idempotent in-app reminder delivery and optional Graph email."""

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce

from activities.mail import send_reminder_email
from activities.models import Reminder, Task
from core.graph_mail import graph_mail_configured

logger = logging.getLogger(__name__)


def deliver_due_reminders(now):
    """Create at most one reminder for each open task and effective due time."""
    due_ids = list(
        Task.objects.filter(status=Task.Status.OPEN, reminder_sent_at__isnull=True)
        .annotate(effective_due=Coalesce("snooze_until", "due_at"))
        .filter(effective_due__lte=now)
        .filter(Q(snooze_until__isnull=True) | Q(snooze_until__lte=now))
        .order_by("due_at", "pk")
        .values_list("pk", flat=True)
    )
    created = 0
    emails = 0
    email_failures = 0
    for task_id in due_ids:
        with transaction.atomic():
            locked = (
                Task.objects.select_for_update().select_related("owner").get(pk=task_id)
            )
            if locked.reminder_sent_at is not None or locked.status != Task.Status.OPEN:
                continue
            effective = locked.snooze_until or locked.due_at
            if effective > now:
                continue
            reminder, was_created = Reminder.objects.get_or_create(
                task=locked,
                recipient=locked.owner,
                due_key=effective.isoformat(),
                defaults={"sent_at": now},
            )
            locked.reminder_sent_at = now
            locked.save(update_fields=("reminder_sent_at",))
            created += int(was_created)
            if graph_mail_configured() and reminder.email_sent_at is None:
                try:
                    if send_reminder_email(reminder):
                        emails += 1
                except ValidationError:
                    email_failures += 1
                    logger.exception(
                        "Reminder email failed",
                        extra={"outcome": "failure", "task_id": str(locked.pk)},
                    )

    if graph_mail_configured():
        pending = (
            Reminder.objects.select_related("task", "recipient")
            .filter(email_sent_at__isnull=True, task__status=Task.Status.OPEN)
            .order_by("pk")[:100]
        )
        for reminder in pending:
            try:
                if send_reminder_email(reminder):
                    emails += 1
            except ValidationError:
                email_failures += 1
                logger.exception(
                    "Reminder email retry failed",
                    extra={"outcome": "failure", "reminder_id": reminder.pk},
                )

    logger.info(
        "Delivered in-app reminders",
        extra={
            "outcome": "success",
            "reminder_count": created,
            "reminder_email_count": emails,
            "reminder_email_failures": email_failures,
        },
    )
    return {
        "reminders": created,
        "reminder_emails": emails,
        "reminder_email_failures": email_failures,
    }
