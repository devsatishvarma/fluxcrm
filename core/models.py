from django.core.exceptions import ValidationError
from django.db import models


class PicklistValue(models.Model):
    """Admin-editable label for a frozen taxonomy key."""

    list_key = models.CharField(max_length=64)
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=120)
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("list_key", "key"),
                name="core_picklist_list_key_uniq",
            )
        ]
        ordering = ("list_key", "order", "key")

    def __str__(self) -> str:
        return f"{self.list_key}:{self.key}"


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Stage history is append-only.")

    def delete(self):
        raise ValidationError("Stage history is append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Stage history is append-only.")


class StageHistory(models.Model):
    """Append-only stage change for a lead or deal."""

    object_type = models.CharField(max_length=16)
    object_id = models.UUIDField()
    from_stage = models.CharField(max_length=64, blank=True)
    to_stage = models.CharField(max_length=64)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        "identity.User",
        null=True,
        on_delete=models.PROTECT,
        related_name="stage_changes",
    )
    duration_seconds = models.PositiveIntegerField(default=0)
    probability_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    probability_reason = models.CharField(max_length=500, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    correction = models.BooleanField(default=False)
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ("changed_at", "pk")
        indexes = [
            models.Index(fields=("object_type", "object_id", "changed_at")),
        ]

    def __str__(self) -> str:
        return f"{self.object_type}:{self.object_id} {self.from_stage}->{self.to_stage}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Stage history is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stage history is append-only.")


class JobRun(models.Model):
    """Idempotency and observability record for scheduled jobs."""

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    name = models.CharField(max_length=100)
    run_key = models.CharField(max_length=150)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("name", "run_key"),
                name="core_jobrun_name_run_key_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("name", "-started_at")),
            models.Index(fields=("status", "-started_at")),
        ]
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.name}:{self.run_key} ({self.status})"
