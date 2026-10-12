"""Customer accounts and the people who work there."""

from django.conf import settings
from django.db import models

from core.records import AuditedRecord


class Account(AuditedRecord):
    """A customer, prospect, or other organization."""

    class Type(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        PROSPECT = "PROSPECT", "Prospect"
        PARTNER = "PARTNER", "Partner"
        REFERRAL = "REFERRAL", "Referral"
        COMPETITOR = "COMPETITOR", "Competitor"
        OEM_VENDOR = "OEM_VENDOR", "OEM Vendor"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    name = models.CharField(max_length=200)
    name_normalized = models.CharField(max_length=200, blank=True, db_index=True)
    account_type = models.CharField(max_length=32, choices=Type.choices)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    industry = models.CharField(max_length=64, blank=True)
    website_url = models.URLField(blank=True)
    website_domain = models.CharField(max_length=253, blank=True, db_index=True)
    phone = models.CharField(max_length=40, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_accounts",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    notes = models.TextField(blank=True)
    converted_from_lead = models.ForeignKey(
        "leads.Lead",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_accounts",
    )

    class Meta:
        ordering = ("name",)
        indexes = [
            models.Index(fields=("owner", "name")),
            models.Index(fields=("deleted_at", "owner")),
            models.Index(fields=("parent",)),
        ]

    def __str__(self) -> str:
        return self.name


class Contact(AuditedRecord):
    """A person at one account."""

    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    title = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    email_normalized = models.CharField(max_length=254, blank=True, db_index=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="contacts",
    )
    is_primary = models.BooleanField(default=False)
    reports_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="direct_reports",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_contacts",
    )
    notes = models.TextField(blank=True)
    converted_from_lead = models.ForeignKey(
        "leads.Lead",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_contacts",
    )

    class Meta:
        ordering = ("last_name", "first_name")
        indexes = [
            models.Index(fields=("account", "is_primary")),
            models.Index(fields=("owner", "last_name")),
            models.Index(fields=("deleted_at", "owner")),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"
