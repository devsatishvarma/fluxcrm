from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from core.display import format_phone, format_whole
from core.validation import clean_email, clean_phone
from identity.models import CompanySettings, Role, Team, User


def _form_phone(value):
    try:
        return clean_phone(value)
    except ValidationError as exc:
        raise ValidationError(exc.messages) from exc


class WholeNumberField(forms.DecimalField):
    """Accept a number, including trailing cents, and keep a whole value."""

    def __init__(self, *args, max_value=None, **kwargs):
        kwargs.setdefault("max_digits", 18)
        kwargs["decimal_places"] = 2
        self.whole_max = max_value
        kwargs.setdefault(
            "widget",
            forms.NumberInput(attrs={"step": "1", "min": "0"}),
        )
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        amount = super().to_python(value)
        if amount in self.empty_values:
            return None
        whole = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if whole < 0 or (self.whole_max is not None and whole > self.whole_max):
            ceiling = "" if self.whole_max is None else f" to {self.whole_max}"
            raise ValidationError(f"Enter a whole number from 0{ceiling}.")
        return whole

    def prepare_value(self, value):
        if value in self.empty_values:
            return ""
        text = format_whole(value)
        return "" if text == "—" else text


ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_LOGO_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp"}
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
            "lead_stale_days",
            "deal_stale_days",
            "logo",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["legal_name"].label = "Legal name"
        self.fields["display_name"].label = "Company name"
        self.fields["display_name"].help_text = "Shown on the home page."
        address = self.instance.address or {}
        self.fields["street"].initial = address.get("street", "")
        self.fields["city"].initial = address.get("city", "")
        self.fields["region"].initial = address.get("region", "")
        self.fields["postal_code"].initial = address.get("postal_code", "")
        self.fields["country"].initial = address.get("country", "")
        self.fields["offered_services_text"].initial = "\n".join(
            self.instance.offered_services or []
        )
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif not isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-control")

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
            "lead_stale_days": self.cleaned_data["lead_stale_days"],
            "deal_stale_days": self.cleaned_data["deal_stale_days"],
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


class GlideLoginForm(AuthenticationForm):
    username = forms.CharField(max_length=150)


class UserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(
        label="Email",
        help_text="Password reset and invitation links are sent to this address.",
    )
    phone = forms.CharField(
        max_length=40,
        required=False,
        label="Phone",
        help_text="Use (XXX) XXX-XXXX. Password reset does not use this number.",
        widget=forms.TextInput(
            attrs={"placeholder": "(XXX) XXX-XXXX", "maxlength": "40"}
        ),
    )
    display_name = forms.CharField(max_length=150)
    timezone = forms.CharField(max_length=64, initial="America/Los_Angeles")
    role = forms.ModelChoiceField(queryset=Role.objects.none())
    manager = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    send_invitation = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Email a single-use password setup link.",
    )
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    password_confirmation = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.order_by("name")
        self.fields["manager"].queryset = User.objects.filter(is_active=True).order_by(
            "display_name"
        )

    def clean_email(self):
        email, _domain = clean_email(self.cleaned_data["email"])
        return email

    def clean_phone(self):
        return _form_phone(self.cleaned_data.get("phone"))

    def clean_timezone(self):
        return _validate_timezone(self.cleaned_data["timezone"])

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirmation")
        if not cleaned.get("send_invitation") and not password:
            self.add_error("password", "Enter a password or send an invitation.")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", "Passwords do not match.")
        if password and not confirmation:
            self.add_error("password_confirmation", "Confirm the password.")
        return cleaned


class ChoiceCheckboxes(forms.CheckboxSelectMultiple):
    """A checkbox list whose label does not toggle the box twice."""

    option_template_name = "core/choice_option.html"


class UserEditForm(forms.Form):
    display_name = forms.CharField(max_length=150, label="Name")
    email = forms.EmailField(
        label="Email",
        help_text="Password reset instructions are sent to this address.",
    )
    phone = forms.CharField(
        max_length=40,
        required=False,
        label="Phone",
        help_text="Use (XXX) XXX-XXXX. Password reset does not use this number.",
        widget=forms.TextInput(
            attrs={"placeholder": "(XXX) XXX-XXXX", "maxlength": "40"}
        ),
    )
    role = forms.ModelChoiceField(queryset=Role.objects.none())
    manager = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    teams = forms.ModelMultipleChoiceField(
        queryset=Team.objects.none(),
        required=False,
        widget=ChoiceCheckboxes,
        help_text="Choose every team this person belongs to.",
    )

    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.order_by("name")
        self.fields["manager"].queryset = (
            User.objects.filter(is_active=True)
            .exclude(pk=instance.pk)
            .order_by("display_name")
        )
        self.fields["teams"].queryset = Team.objects.order_by("name")
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif not isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault("class", "form-control")
        if not self.is_bound:
            self.initial.update(
                {
                    "display_name": instance.display_name,
                    "email": instance.email,
                    "phone": format_phone(instance.phone, empty=""),
                    "role": instance.role_id,
                    "manager": instance.manager_id,
                    "teams": list(instance.teams.values_list("pk", flat=True)),
                }
            )

    def clean_email(self):
        email, _domain = clean_email(self.cleaned_data["email"])
        return email

    def clean_phone(self):
        return _form_phone(self.cleaned_data.get("phone"))


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
    if Path(upload.name).suffix.lower() not in ALLOWED_LOGO_EXTENSIONS:
        raise ValidationError("Logo files must use .png, .jpg, .jpeg, or .webp.")
    position = upload.tell()
    header = upload.read(12)
    upload.seek(position)
    valid_signature = (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )
    if not valid_signature:
        raise ValidationError("The uploaded file is not a valid PNG, JPEG, or WebP.")
    return upload
