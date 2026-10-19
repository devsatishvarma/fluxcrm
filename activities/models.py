"""Follow-up activities, tasks, and in-app reminders."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Q
from django.urls import reverse

from core.records import AuditedRecord


class Activity(AuditedRecord):
    """One logged interaction that can appear on several CRM records."""

    class Type(models.TextChoices):
        CALL = "CALL", "Call"
        EMAIL = "EMAIL", "Email"
        MEETING = "MEETING", "Meeting"
        NOTE = "NOTE", "Note"

    activity_type = models.CharField(max_length=16, choices=Type.choices)
    subject = models.CharField(max_length=200)
    with_whom = models.CharField(max_length=200, blank=True, default="")
    with_contact = models.ForeignKey(
        "accounts.Contact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activities_with",
    )
    with_lead = models.ForeignKey(
        "leads.Lead",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activities_with",
    )
    body = models.TextField(blank=True)
    occurred_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=200, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_activities",
    )
    source = models.CharField(max_length=16, default="MANUAL")

    class Meta:
        ordering = ("-occurred_at", "-created_at")
        indexes = [
            models.Index(fields=("owner", "occurred_at")),
            models.Index(fields=("deleted_at", "owner")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(with_contact__isnull=False, with_lead__isnull=False),
                name="activities_activity_one_party",
            )
        ]

    def __str__(self) -> str:
        return self.subject

    def party_value(self):
        if self.with_contact_id:
            return f"contact:{self.with_contact_id}"
        if self.with_lead_id:
            return f"lead:{self.with_lead_id}"
        return ""

    def party_name(self):
        record = self._party_record()
        if record is not None:
            return f"{record.first_name} {record.last_name}".strip()
        return self.with_whom

    def party_url(self):
        record = self._party_record()
        if record is None:
            return ""
        if self.with_contact_id:
            return reverse("accounts:detail", args=[record.account_id])
        return reverse("leads:detail", args=[record.pk])

    def _party_record(self):
        if self.with_contact_id:
            try:
                return self.with_contact
            except ObjectDoesNotExist:
                return None
        if self.with_lead_id:
            try:
                return self.with_lead
            except ObjectDoesNotExist:
                return None
        return None


class ActivityLink(models.Model):
    """Connects one activity to one lead or deal without copying it."""

    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="links",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.UUIDField()
    record = GenericForeignKey("content_type", "object_id")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("activity", "content_type", "object_id"),
                name="activities_link_activity_object_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("content_type", "object_id")),
        ]

    def __str__(self) -> str:
        return f"{self.activity_id}:{self.object_id}"


class Task(AuditedRecord):
    """A follow-up owned by one user and linked to CRM records."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        HOLD = "HOLD", "On hold"
        DONE = "DONE", "Done"
        CANCELLED = "CANCELLED", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
    )
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_tasks",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    snooze_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("due_at", "created_at")
        indexes = [
            models.Index(fields=("owner", "status", "due_at")),
            models.Index(fields=("status", "reminder_sent_at", "due_at")),
            models.Index(fields=("deleted_at", "owner")),
        ]

    def __str__(self) -> str:
        return self.title


class TaskLink(models.Model):
    """Connects one task to one lead or deal."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="links")
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.UUIDField()
    record = GenericForeignKey("content_type", "object_id")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("task", "content_type", "object_id"),
                name="activities_tasklink_task_object_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("content_type", "object_id")),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.object_id}"


class Reminder(models.Model):
    """One in-app reminder for a task, recipient, and effective due time."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reminders")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    due_key = models.CharField(max_length=40)
    sent_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("task", "recipient", "due_key"),
                name="activities_reminder_task_recipient_due_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("recipient", "sent_at")),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.due_key}"
