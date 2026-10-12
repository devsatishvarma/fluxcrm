"""Lead capture forms. Business rules are enforced by the lead service."""

from django import forms

from core.taxonomy import choice_pairs
from identity.models import User


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
    email = forms.EmailField(required=False)
    work_phone = forms.CharField(max_length=40, required=False)
    mobile_phone = forms.CharField(max_length=40, required=False)
    company_name = forms.CharField(max_length=200)
    website_url = forms.CharField(max_length=200, required=False)
    industry = forms.ChoiceField(required=False)
    company_size_band = forms.ChoiceField(required=False)
    employee_count = forms.IntegerField(min_value=0, required=False)
    annual_revenue = forms.DecimalField(max_digits=18, decimal_places=2, required=False)
    source = forms.ChoiceField()
    contact_substatus = forms.ChoiceField(required=False)
    nurture_reason = forms.ChoiceField(required=False)
    disqualification_reason = forms.ChoiceField(required=False)
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
        self.fields["source"].choices = choice_pairs("LEAD_SOURCE")
        self.fields["contact_substatus"].choices = choice_pairs("CONTACT_SUBSTATUS")
        self.fields["nurture_reason"].choices = choice_pairs("NURTURE_REASON")
        self.fields["disqualification_reason"].choices = choice_pairs(
            "DISQUALIFICATION_REASON"
        )
        self.fields["owner"].queryset = User.objects.filter(is_active=True).order_by(
            "display_name"
        )
        if not user.is_company_admin:
            self.fields.pop("owner")
        if instance is not None and not self.is_bound:
            for name in self.fields:
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
        _style(self)

    def service_data(self):
        data = dict(self.cleaned_data)
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
    delete_reason = forms.CharField(max_length=200)
