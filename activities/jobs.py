"""Idempotent in-app reminder delivery."""

import logging

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce

from activities.models import Reminder, Task

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
            _, was_created = Reminder.objects.get_or_create(
                task=locked,
                recipient=locked.owner,
                due_key=effective.isoformat(),
                defaults={"sent_at": now},
            )
            locked.reminder_sent_at = now
            locked.save(update_fields=("reminder_sent_at",))
            created += int(was_created)
    logger.info(
        "Delivered in-app reminders",
        extra={"outcome": "success", "reminder_count": created},
    )
    return {"reminders": created}
