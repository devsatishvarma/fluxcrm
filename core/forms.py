from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from identity.models import CompanySettings, Role, User

ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024
DEFAULT_SERVICES = [
    "IT Consulting",
    "Professional Services",
    "Managed Services",
    "Value Added Reseller",
]


class SetupForm(forms.Form):
    legal_name = forms.CharField(max_length=200, initial="Infoshare Systems Inc.")
    display_name = forms.CharField(max_length=200, initial="Infoshare Systems")
    street = forms.CharField(max_length=200, initial="26040 Acero")
    city = forms.CharField(max_length=100, initial="Mission Viejo")
    region = forms.CharField(max_length=100, initial="CA")
    postal_code = forms.CharField(max_length=20, initial="92691")
    country = forms.CharField(max_length=2, initial="US")
    industry = forms.CharField(max_length=120, initial="Information Technology")
    offered_services = forms.CharField(
        widget=forms.Textarea,
        initial="\n".join(DEFAULT_SERVICES),
        help_text="Enter one service per line.",
    )
    base_currency = forms.CharField(max_length=3, initial="USD")
    fiscal_year_start_month = forms.IntegerField(
        min_value=1,
        max_value=12,
        initial=1,
    )
    default_timezone = forms.CharField(max_length=64, initial="America/Los_Angeles")
    logo = forms.FileField(required=False)
    admin_username = forms.CharField(max_length=150)
    admin_email = forms.EmailField()
    admin_display_name = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirmation = forms.CharField(widget=forms.PasswordInput)

    def clean_base_currency(self):
        currency = self.cleaned_data["base_currency"].upper()
        if currency != "USD":
            raise ValidationError("Phase 1 supports the company base currency USD.")
        return currency

    def clean_default_timezone(self):
        return _validate_timezone(self.cleaned_data["default_timezone"])

    def clean_logo(self):
        return _validate_logo(self.cleaned_data.get("logo"))

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", "Passwords do not match.")
        return cleaned

    def company_profile(self) -> dict:
        services = [
            line.strip()
            for line in self.cleaned_data["offered_services"].splitlines()
            if line.strip()
        ]
        profile = {
            "legal_name": self.cleaned_data["legal_name"],
            "display_name": self.cleaned_data["display_name"],
            "address": {
                "street": self.cleaned_data["street"],
                "city": self.cleaned_data["city"],
                "region": self.cleaned_data["region"],
                "postal_code": self.cleaned_data["postal_code"],
                "country": self.cleaned_data["country"],
            },
            "industry": self.cleaned_data["industry"],
            "offered_services": services,
            "base_currency": self.cleaned_data["base_currency"],
            "fiscal_year_start_month": self.cleaned_data["fiscal_year_start_month"],
            "default_timezone": self.cleaned_data["default_timezone"],
        }
        if self.cleaned_data.get("logo"):
            profile["logo"] = self.cleaned_data["logo"]
        return profile


class CompanySettingsForm(forms.ModelForm):
    street = forms.CharField(max_length=200)
    city = forms.CharField(max_length=100)
    region = forms.CharField(max_length=100)
    postal_code = forms.CharField(max_length=20)
    country = forms.CharField(max_length=2)
    offered_services_text = forms.CharField(
        widget=forms.Textarea,
        label="Offered services",
    )

    class Meta:
        model = CompanySettings
        fields = (
            "legal_name",
            "display_name",
            "industry",
            "base_currency",
            "fiscal_year_start_month",
            "default_timezone",
            "logo",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        address = self.instance.address or {}
        self.fields["street"].initial = address.get("street", "")
        self.fields["city"].initial = address.get("city", "")
        self.fields["region"].initial = address.get("region", "")
        self.fields["postal_code"].initial = address.get("postal_code", "")
        self.fields["country"].initial = address.get("country", "")
        self.fields["offered_services_text"].initial = "\n".join(
            self.instance.offered_services or []
        )

    def clean_base_currency(self):
        currency = self.cleaned_data["base_currency"].upper()
        if currency != "USD":
            raise ValidationError("Phase 1 supports the company base currency USD.")
        return currency

    def clean_default_timezone(self):
        return _validate_timezone(self.cleaned_data["default_timezone"])

    def clean_logo(self):
        return _validate_logo(self.cleaned_data.get("logo"))

    def profile_changes(self) -> dict:
        services = [
            line.strip()
            for line in self.cleaned_data["offered_services_text"].splitlines()
            if line.strip()
        ]
        changes = {
            "legal_name": self.cleaned_data["legal_name"],
            "display_name": self.cleaned_data["display_name"],
            "industry": self.cleaned_data["industry"],
            "base_currency": self.cleaned_data["base_currency"],
            "fiscal_year_start_month": self.cleaned_data["fiscal_year_start_month"],
            "default_timezone": self.cleaned_data["default_timezone"],
            "address": {
                "street": self.cleaned_data["street"],
                "city": self.cleaned_data["city"],
                "region": self.cleaned_data["region"],
                "postal_code": self.cleaned_data["postal_code"],
                "country": self.cleaned_data["country"],
            },
            "offered_services": services,
        }
        if self.cleaned_data.get("logo"):
            changes["logo"] = self.cleaned_data["logo"]
        return changes


class FluxLoginForm(AuthenticationForm):
    username = forms.CharField(max_length=150)


class UserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    display_name = forms.CharField(max_length=150)
    timezone = forms.CharField(max_length=64, initial="America/Los_Angeles")
    role = forms.ModelChoiceField(queryset=Role.objects.none())
    manager = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirmation = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.order_by("name")
        self.fields["manager"].queryset = User.objects.filter(is_active=True).order_by(
            "display_name"
        )

    def clean_timezone(self):
        return _validate_timezone(self.cleaned_data["timezone"])

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", "Passwords do not match.")
        return cleaned


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError("Enter a valid IANA time zone.") from exc
    return value


def _validate_logo(upload):
    if not upload:
        return upload
    if upload.size > MAX_LOGO_BYTES:
        raise ValidationError("Logo files must be 2 MB or smaller.")
    content_type = getattr(upload, "content_type", "")
    if content_type not in ALLOWED_LOGO_TYPES:
        raise ValidationError("Logo files must be PNG, JPEG, or WebP.")
    return upload
