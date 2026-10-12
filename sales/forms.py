"""Deal capture forms. Business rules are enforced by the deal service."""

from django import forms

from core.access import scoped
from core.taxonomy import choice_pairs
from identity.models import User
from leads.forms import _style
from leads.models import Lead


class DealForm(forms.Form):
    title = forms.CharField(max_length=200)
    lead = forms.ModelChoiceField(queryset=Lead.objects.none())
    deal_type = forms.ChoiceField()
    amount = forms.DecimalField(max_digits=18, decimal_places=2, required=False)
    currency = forms.CharField(max_length=3, initial="USD")
    temperature = forms.ChoiceField()
    expected_close_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    probability = forms.DecimalField(max_digits=5, decimal_places=2, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)
    owner = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead"].queryset = scoped(
            Lead.objects.select_related("owner"), user
        ).order_by("company_name", "last_name")
        self.fields["deal_type"].choices = choice_pairs("DEAL_TYPE")
        self.fields["temperature"].choices = choice_pairs("TEMPERATURE")
        self.fields["owner"].queryset = User.objects.filter(is_active=True).order_by(
            "display_name"
        )
        if not user.is_company_admin:
            self.fields.pop("owner")
        if instance is not None and not self.is_bound:
            self.initial.update(
                {
                    "title": instance.title,
                    "lead": instance.lead_id,
                    "deal_type": instance.deal_type,
                    "amount": instance.amount,
                    "currency": instance.currency,
                    "temperature": instance.temperature,
                    "expected_close_date": instance.expected_close_date,
                    "probability": instance.probability,
                    "notes": instance.notes,
                    "version": instance.version,
                }
            )
            if "owner" in self.fields:
                self.initial["owner"] = instance.owner_id
        _style(self)

    def service_data(self):
        data = dict(self.cleaned_data)
        lead = data.get("lead")
        if lead is not None:
            data["lead"] = lead.pk
        owner = data.get("owner")
        if owner is not None:
            data["owner"] = owner.pk
        else:
            data.pop("owner", None)
        if data.get("expected_close_date"):
            data["expected_close_date"] = data["expected_close_date"].isoformat()
        if not data.get("version"):
            data.pop("version", None)
        return data


class DealDeleteForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    delete_reason = forms.CharField(max_length=200)
