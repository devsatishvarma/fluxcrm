"""Deal capture forms. Business rules are enforced by the deal service."""

from django import forms

from accounts.models import Account, Contact
from core.access import scoped
from core.forms import WholeNumberField
from core.policy import assignable_users
from core.taxonomy import choice_pairs
from identity.models import User
from leads.forms import _style
from leads.models import Lead


def _lead_label(lead):
    name = f"{lead.first_name} {lead.last_name}".strip()
    company = str(lead.company_name or "").strip()
    if company:
        return f"{name} ({company})"
    return name


class DealForm(forms.Form):
    title = forms.CharField(max_length=200)
    lead = forms.ModelChoiceField(queryset=Lead.objects.none())
    deal_type = forms.ChoiceField()
    amount = WholeNumberField(required=False)
    currency = forms.CharField(max_length=3, initial="USD")
    expected_close_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    actual_close_date = forms.DateField(
        label="Actual close date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text=(
            "The day the deal closed. Wins are counted on this date, "
            "not the day the stage changed."
        ),
    )
    evaluation_started_on = forms.DateField(
        label="POC or trial start",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    probability = WholeNumberField(
        label="Win probability",
        required=False,
        max_value=100,
        widget=forms.NumberInput(attrs={"step": "1", "min": "0", "max": "100"}),
        help_text=(
            "A whole percent, such as 30. Deal confidence is set from this "
            "number. High is 80% or more, Medium is 40% up to 80%, and Low "
            "is under 40%."
        ),
    )
    probability_reason = forms.CharField(
        label="Why the probability changed",
        max_length=500,
        required=False,
        help_text=(
            "Required when the win probability changes. "
            "Leave blank if it stays the same."
        ),
    )
    bant_budget_status = forms.ChoiceField(label="Budget", required=False)
    bant_authority_status = forms.ChoiceField(label="Authority", required=False)
    bant_need_status = forms.ChoiceField(label="Need", required=False)
    bant_timeline_status = forms.ChoiceField(label="Timeline", required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)
    owner = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user, instance=None, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account
        self.choose_source = account is None and instance is None
        self.contact_options = []
        leads = scoped(Lead.objects.select_related("owner"), user).order_by(
            "company_name", "last_name", "first_name"
        )
        if self.choose_source:
            self.fields["linked_to"] = forms.ChoiceField(
                label="This deal is linked to",
                choices=(
                    ("", "Select"),
                    ("lead", "A lead"),
                    ("account", "An account"),
                ),
                required=False,
            )
            self.fields["lead"].queryset = leads
            self.fields["lead"].required = False
            self.fields["lead"].empty_label = "Select a lead"
            self.fields["lead"].label = "Lead"
            self.fields["lead"].help_text = "The person this deal is with."
            self.fields["lead"].label_from_instance = _lead_label
            self.fields["account"] = forms.ModelChoiceField(
                label="Account",
                queryset=scoped(Account.objects.all(), user).order_by("name"),
                required=False,
                empty_label="Select an account",
            )
            contacts = scoped(Contact.objects.select_related("account"), user).order_by(
                "last_name", "first_name"
            )
            self.contact_options = [
                {
                    "id": str(contact.pk),
                    "account": str(contact.account_id),
                    "name": str(contact),
                }
                for contact in contacts
            ]
            self.fields["primary_contact"] = forms.ModelChoiceField(
                label="Contact",
                queryset=contacts,
                required=False,
                empty_label="Select a contact",
                help_text="A person already on that account.",
            )
            contact_choices = [("", "Select a contact")]
            posted_contact = str(self.data.get("primary_contact") or "")
            posted_account = str(self.data.get("account") or "")
            if posted_contact:
                match = next(
                    (
                        item
                        for item in self.contact_options
                        if item["id"] == posted_contact
                        and (not posted_account or item["account"] == posted_account)
                    ),
                    None,
                )
                if match is not None:
                    contact_choices.append((match["id"], match["name"]))
            self.fields["primary_contact"].choices = contact_choices
        elif account is None:
            self.fields["lead"].queryset = leads
        else:
            self.fields.pop("lead")
            self.fields["account"] = forms.CharField(
                required=True,
                widget=forms.HiddenInput,
                initial=str(account.pk),
            )
            self.fields["primary_contact"] = forms.ModelChoiceField(
                label="Contact",
                queryset=scoped(Contact.objects.filter(account=account), user).order_by(
                    "last_name", "first_name"
                ),
                empty_label="Select a contact",
                help_text="The person on this account this deal is with.",
            )
            names = [name for name in self.fields if name != "primary_contact"]
            names.insert(names.index("title") + 1, "primary_contact")
            self.order_fields(names)
        self.fields["deal_type"].choices = choice_pairs("DEAL_TYPE")
        bant_choices = [pair for pair in choice_pairs("BANT_STATUS") if pair[0]]
        for name in (
            "bant_budget_status",
            "bant_authority_status",
            "bant_need_status",
            "bant_timeline_status",
        ):
            self.fields[name].choices = bant_choices
            self.fields[name].initial = "UNKNOWN"
        owners = assignable_users(user, "deal")
        self.fields["owner"].queryset = owners
        if owners.count() <= 1:
            self.fields.pop("owner")
        if instance is None:
            self.fields.pop("probability_reason")
        if self.choose_source:
            names = [
                name
                for name in self.fields
                if name not in {"linked_to", "lead", "account", "primary_contact"}
            ]
            insert_at = names.index("title") + 1
            for name in ("linked_to", "lead", "account", "primary_contact"):
                names.insert(insert_at, name)
                insert_at += 1
            self.order_fields(names)
        if instance is not None and not self.is_bound:
            self.initial.update(
                {
                    "title": instance.title,
                    "lead": instance.lead_id,
                    "primary_contact": instance.primary_contact_id,
                    "deal_type": instance.deal_type,
                    "amount": instance.amount,
                    "currency": instance.currency,
                    "expected_close_date": instance.expected_close_date,
                    "actual_close_date": instance.actual_close_date,
                    "evaluation_started_on": instance.evaluation_started_on,
                    "probability": instance.probability,
                    "bant_budget_status": instance.bant_budget_status,
                    "bant_authority_status": instance.bant_authority_status,
                    "bant_need_status": instance.bant_need_status,
                    "bant_timeline_status": instance.bant_timeline_status,
                    "notes": instance.notes,
                    "version": instance.version,
                }
            )
            if "owner" in self.fields:
                self.initial["owner"] = instance.owner_id
        _style(self)

    def clean(self):
        cleaned = super().clean()
        if not self.choose_source:
            return cleaned
        linked = cleaned.get("linked_to") or ""
        lead = cleaned.get("lead")
        account = cleaned.get("account")
        contact = cleaned.get("primary_contact")
        if linked not in {"lead", "account"}:
            if lead is not None and account is None:
                linked = "lead"
            elif account is not None and lead is None:
                linked = "account"
            else:
                self.add_error(
                    "linked_to",
                    "Choose whether this deal is linked to a lead or an account.",
                )
                return cleaned
        if linked == "lead":
            if lead is None:
                self.add_error("lead", "Select a lead.")
            cleaned["account"] = None
            cleaned["primary_contact"] = None
        else:
            cleaned["lead"] = None
            if account is None:
                self.add_error("account", "Select an account.")
            elif contact is None or contact.account_id != account.pk:
                self.add_error("primary_contact", "Select a contact on this account.")
        cleaned["linked_to"] = linked
        return cleaned

    def service_data(self):
        data = dict(self.cleaned_data)
        data.pop("linked_to", None)
        lead = data.get("lead")
        if lead is not None:
            data["lead"] = lead.pk
        contact = data.get("primary_contact")
        if contact is not None:
            data["primary_contact"] = contact.pk
        account = data.get("account")
        if getattr(account, "pk", None):
            data["account"] = account.pk
        elif account:
            data["account"] = str(account)
        else:
            data.pop("account", None)
        owner = data.get("owner")
        if owner is not None:
            data["owner"] = owner.pk
        else:
            data.pop("owner", None)
        if data.get("expected_close_date"):
            data["expected_close_date"] = data["expected_close_date"].isoformat()
        if data.get("actual_close_date"):
            data["actual_close_date"] = data["actual_close_date"].isoformat()
        if data.get("evaluation_started_on"):
            data["evaluation_started_on"] = data["evaluation_started_on"].isoformat()
        if not data.get("version"):
            data.pop("version", None)
        return data


class DealDeleteForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    delete_reason = forms.CharField(
        label="Reason for deletion",
        min_length=3,
        max_length=200,
        widget=forms.TextInput(attrs={"minlength": "3", "maxlength": "200"}),
    )
