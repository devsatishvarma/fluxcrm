"""Lead capture forms. Business rules are enforced by the lead service."""

from django import forms
from django.core.exceptions import ValidationError

from core.display import format_phone
from core.forms import WholeNumberField
from core.policy import assignable_users
from core.taxonomy import choice_pairs
from core.validation import clean_phone
from identity.models import User


def _form_phone(value, field):
    try:
        return clean_phone(value, field=field)
    except ValidationError as exc:
        raise ValidationError(exc.messages) from exc


def _style(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        elif not isinstance(widget, forms.HiddenInput):
            widget.attrs.setdefault("class", "form-control")


class LeadForm(forms.Form):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    title = forms.CharField(max_length=120, required=False)
    email = forms.EmailField()
    work_phone = forms.CharField(
        label="Work phone",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "(XXX) XXX-XXXX", "maxlength": "40"}
        ),
    )
    mobile_phone = forms.CharField(
        label="Mobile phone",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "(XXX) XXX-XXXX", "maxlength": "40"}
        ),
    )
    street = forms.CharField(label="Street", max_length=200, required=False)
    city = forms.CharField(label="City", max_length=100, required=False)
    region = forms.CharField(label="State", max_length=100, required=False)
    postal_code = forms.CharField(label="Postal code", max_length=20, required=False)
    country = forms.CharField(label="Country", max_length=100, required=False)
    company_name = forms.CharField(max_length=200)
    website_url = forms.CharField(max_length=200, required=False)
    industry = forms.ChoiceField(required=False)
    company_size_band = forms.ChoiceField(label="Company size", required=False)
    current_tools = forms.ChoiceField(label="Current tools", required=False)
    budget_range = forms.ChoiceField(label="Budget range", required=False)
    buying_timeline = forms.ChoiceField(label="Timeline", required=False)
    annual_revenue = WholeNumberField(label="Annual revenue", required=False)
    source = forms.ChoiceField()
    rating = forms.ChoiceField(label="Lead rating", required=False)
    contact_substatus = forms.ChoiceField(required=False)
    nurture_reason = forms.ChoiceField(required=False)
    disqualification_reason = forms.ChoiceField(required=False)
    demo_scheduled_on = forms.DateField(
        label="Demo date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    technical_contact_name = forms.CharField(
        label="Technical contact",
        max_length=120,
        required=False,
    )
    next_follow_up_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    notes = forms.CharField(required=False, widget=forms.Textarea)
    owner = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["industry"].choices = choice_pairs("INDUSTRY")
        self.fields["company_size_band"].choices = choice_pairs("COMPANY_SIZE")
        self.fields["current_tools"].choices = choice_pairs("CURRENT_TOOLS")
        self.fields["budget_range"].choices = choice_pairs("BUDGET_RANGE")
        self.fields["buying_timeline"].choices = choice_pairs("BUYING_TIMELINE")
        self.fields["source"].choices = choice_pairs("LEAD_SOURCE")
        self.fields["rating"].choices = choice_pairs("LEAD_RATING")
        self.fields["rating"].initial = "WARM"
        self.fields["contact_substatus"].choices = choice_pairs("CONTACT_SUBSTATUS")
        self.fields["nurture_reason"].choices = choice_pairs("NURTURE_REASON")
        self.fields["disqualification_reason"].choices = choice_pairs(
            "DISQUALIFICATION_REASON"
        )
        owners = assignable_users(user, "lead")
        self.fields["owner"].queryset = owners
        if owners.count() <= 1:
            self.fields.pop("owner")
        if instance is not None and not self.is_bound:
            address = instance.address or {}
            for part in ("street", "city", "region", "postal_code", "country"):
                self.initial[part] = address.get(part, "")
            for name in self.fields:
                if name in {"street", "city", "region", "postal_code", "country"}:
                    continue
                if name == "version":
                    self.initial[name] = instance.version
                elif name == "owner":
                    self.initial[name] = instance.owner_id
                elif name == "next_follow_up_at" and instance.next_follow_up_at:
                    self.initial[name] = instance.next_follow_up_at.strftime(
                        "%Y-%m-%dT%H:%M"
                    )
                elif hasattr(instance, name):
                    self.initial[name] = getattr(instance, name)
            for part in ("work_phone", "mobile_phone"):
                self.initial[part] = format_phone(self.initial.get(part), empty="")
        _style(self)

    def clean_work_phone(self):
        return _form_phone(self.cleaned_data.get("work_phone"), "work_phone")

    def clean_mobile_phone(self):
        return _form_phone(self.cleaned_data.get("mobile_phone"), "mobile_phone")

    def service_data(self):
        data = dict(self.cleaned_data)
        data["address"] = {
            "street": data.pop("street", "") or "",
            "city": data.pop("city", "") or "",
            "region": data.pop("region", "") or "",
            "postal_code": data.pop("postal_code", "") or "",
            "country": data.pop("country", "") or "",
        }
        owner = data.get("owner")
        if owner is not None:
            data["owner"] = owner.pk
        else:
            data.pop("owner", None)
        if not data.get("version"):
            data.pop("version", None)
        return data


class LeadDeleteForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    delete_reason = forms.CharField(
        label="Reason for deletion",
        min_length=3,
        max_length=200,
        widget=forms.TextInput(attrs={"minlength": "3", "maxlength": "200"}),
    )
