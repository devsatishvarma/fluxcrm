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
