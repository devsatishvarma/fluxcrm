import uuid
from pathlib import Path

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


def company_logo_path(instance, filename):
    """Store uploads under a random key, never the supplied filename."""
    extension = Path(filename).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        extension = ""
    return f"company-logo/{uuid.uuid4().hex}{extension}"


class Role(models.Model):
    """Object, action, and scope grants. ``grants_version`` bumps on each edit."""

    key = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=dict)
    scope_policy = models.CharField(max_length=32, default="OWN")
    grants_version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Internal GlideCRM user. CRM customer records stay in the accounts app."""

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=40, blank=True, default="")
    display_name = models.CharField(max_length=150)
    timezone = models.CharField(max_length=64, default="America/Los_Angeles")
    manager = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="direct_reports",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="users",
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)

    REQUIRED_FIELDS = ["email", "display_name"]

    def clean(self):
        super().clean()
        ancestor = self.manager
        seen = {self.pk} if self.pk else set()
        while ancestor is not None:
            if ancestor.pk == self.pk or ancestor.pk in seen:
                raise ValidationError(
                    {"manager": "Reporting relationships cannot contain a cycle."}
                )
            seen.add(ancestor.pk)
            ancestor = ancestor.manager

    @property
    def is_company_admin(self) -> bool:
        return self.role_id is not None and self.role.key == "ADMIN"

    def __str__(self) -> str:
        return self.display_name or self.username


class Team(models.Model):
    """Optional grouping. Record visibility still follows the manager tree."""

    name = models.CharField(max_length=80, unique=True)
    manager = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="managed_teams",
    )
    members = models.ManyToManyField(User, blank=True, related_name="teams")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class CompanySettings(models.Model):
    """The single configured company profile."""

    singleton = models.BooleanField(default=True, editable=False, unique=True)
    legal_name = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200)
    address = models.JSONField(default=dict)
    industry = models.CharField(max_length=120, blank=True)
    offered_services = models.JSONField(default=list)
    base_currency = models.CharField(
        max_length=3,
        default="USD",
        validators=[RegexValidator(r"^[A-Z]{3}$")],
    )
    fiscal_year_start_month = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    default_timezone = models.CharField(max_length=64, default="America/Los_Angeles")
    lead_stale_days = models.PositiveSmallIntegerField(
        default=14,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    deal_stale_days = models.PositiveSmallIntegerField(
        default=21,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    logo = models.FileField(upload_to=company_logo_path, blank=True)

    def __str__(self) -> str:
        return self.display_name


class AuthThrottle(models.Model):
    """Database-backed limiter for login and password-reset attempts."""

    scope = models.CharField(max_length=32)
    subject_hash = models.CharField(max_length=64)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=("scope", "subject_hash", "attempted_at")),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.subject_hash[:8]}"
