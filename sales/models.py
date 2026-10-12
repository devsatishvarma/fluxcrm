"""Deals linked to exactly one lead or one account."""

from django.conf import settings
from django.db import models

from accounts.models import Account, Contact
from core.records import AuditedRecord
from leads.models import Lead


class Deal(AuditedRecord):
    """A sales deal that belongs to a lead or, after conversion, an account."""

    title = models.CharField(max_length=200)
    lead = models.ForeignKey(
        Lead,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deals",
    )
    account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deals",
    )
    primary_contact = models.ForeignKey(
        Contact,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="primary_deals",
    )
    converted_from_lead = models.ForeignKey(
        Lead,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="converted_deals",
    )
    deal_type = models.CharField(max_length=64)
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=3, default="USD")
    confidence = models.CharField(max_length=16)
    expected_close_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_deals",
    )
    stage = models.CharField(max_length=64)
    stage_entered_at = models.DateTimeField()
    probability = models.DecimalField(max_digits=5, decimal_places=2)
    notes = models.TextField(blank=True)
    bant_budget_status = models.CharField(max_length=16, default="UNKNOWN")
    bant_authority_status = models.CharField(max_length=16, default="UNKNOWN")
    bant_need_status = models.CharField(max_length=16, default="UNKNOWN")
    bant_timeline_status = models.CharField(max_length=16, default="UNKNOWN")
    close_reason = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=16, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "stage", "created_at")),
            models.Index(fields=("owner", "updated_at")),
            models.Index(fields=("deleted_at", "owner")),
            models.Index(fields=("lead", "stage")),
            models.Index(fields=("account", "stage")),
            models.Index(fields=("expected_close_date",)),
            models.Index(fields=("stage", "created_at")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(lead__isnull=False, account__isnull=True)
                    | models.Q(lead__isnull=True, account__isnull=False)
                ),
                name="sales_deal_lead_xor_account",
            )
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title
