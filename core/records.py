"""Shared identity, audit, and soft-delete columns for CRM records."""

import uuid

from django.conf import settings
from django.db import models


class AliveQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)


class AliveManager(models.Manager.from_queryset(AliveQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AuditedRecord(models.Model):
    """UUID identity, optimistic version, and soft delete."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    delete_reason = models.CharField(max_length=200, blank=True)

    objects = AliveManager()
    all_objects = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True
