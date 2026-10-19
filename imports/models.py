"""Staged CSV batches. Business records are created only on commit."""

import uuid

from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """One uploaded CSV, from preview through commit or rollback."""

    class Status(models.TextChoices):
        PREVIEW = "preview", "Preview"
        COMMITTED = "committed", "Committed"
        INCOMPLETE = "incomplete", "Incomplete"
        ROLLED_BACK = "rolled_back", "Rolled back"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="import_batches",
    )
    entity = models.CharField(max_length=16)
    policy = models.CharField(max_length=16, default="skip")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PREVIEW,
    )
    idempotency_key = models.CharField(max_length=64, blank=True)
    filename = models.CharField(max_length=255)
    payload = models.FileField(upload_to="import_staging/%Y/%m/")
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("actor", "created_at")),
            models.Index(fields=("actor", "idempotency_key")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("actor", "idempotency_key"),
                condition=~models.Q(idempotency_key=""),
                name="imports_batch_actor_key_uniq",
            )
        ]

    def __str__(self):
        return f"{self.entity} {self.status}"


class ImportRow(models.Model):
    """One committed, skipped, or conflicting row. Preview errors stay on the batch."""

    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.PositiveIntegerField()
    outcome = models.CharField(max_length=16)
    object_id = models.CharField(max_length=64, blank=True)
    external_id = models.CharField(max_length=64, blank=True)
    before_json = models.JSONField(null=True, blank=True)
    after_version = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ("row_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "row_number"),
                name="imports_row_batch_number_uniq",
            )
        ]

    def __str__(self):
        return f"{self.row_number} {self.outcome}"
