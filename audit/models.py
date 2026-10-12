from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionDenied("Audit history cannot be changed.")

    def delete(self):
        raise PermissionDenied("Audit history cannot be changed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionDenied("Audit history cannot be changed.")


class AuditEvent(models.Model):
    """Append-only record of security-relevant state changes."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=32, default="web")
    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=("object_type", "object_id", "occurred_at")),
            models.Index(fields=("actor", "occurred_at")),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.object_type}:{self.object_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionDenied("Audit history cannot be changed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Audit history cannot be changed.")
