"""Prospective person and organization, before Account conversion."""

from django.conf import settings
from django.db import models

from core.records import AuditedRecord


class Lead(AuditedRecord):
    """One person and the organization they represent."""

    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    title = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    email_normalized = models.CharField(max_length=254, blank=True, db_index=True)
    email_domain = models.CharField(max_length=253, blank=True)
    work_phone = models.CharField(max_length=40, blank=True)
    mobile_phone = models.CharField(max_length=40, blank=True)
    address = models.JSONField(default=dict, blank=True)
    company_name = models.CharField(max_length=200)
    website_url = models.URLField(blank=True)
    website_domain = models.CharField(max_length=253, blank=True, db_index=True)
    industry = models.CharField(max_length=64, blank=True)
    products_services = models.CharField(max_length=255, blank=True)
    company_size_band = models.CharField(max_length=64, blank=True)
    employee_count = models.PositiveIntegerField(null=True, blank=True)
    annual_revenue = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    source = models.CharField(max_length=64)
    rating = models.CharField(max_length=16, default="WARM")
    stage = models.CharField(max_length=64)
    contact_substatus = models.CharField(max_length=64, blank=True)
    stage_entered_at = models.DateTimeField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_leads",
    )
    nurture_reason = models.CharField(max_length=64, blank=True)
    disqualification_reason = models.CharField(max_length=64, blank=True)
    next_follow_up_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="converted_leads",
    )
    converted_contact = models.ForeignKey(
        "accounts.Contact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="converted_leads",
    )

    class Meta:
        indexes = [
            models.Index(fields=("owner", "stage", "created_at")),
            models.Index(fields=("owner", "updated_at")),
            models.Index(fields=("deleted_at", "owner")),
            models.Index(fields=("stage", "created_at")),
            models.Index(fields=("next_follow_up_at",)),
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"
