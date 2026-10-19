from django.db import migrations, models


def link_saved_names(apps, schema_editor):
    """Attach a saved name when it matches one contact or one lead."""
    Activity = apps.get_model("activities", "Activity")
    Contact = apps.get_model("accounts", "Contact")
    Lead = apps.get_model("leads", "Lead")
    contacts = {}
    for contact in Contact.objects.filter(deleted_at__isnull=True):
        key = f"{contact.first_name} {contact.last_name}".strip().casefold()
        contacts.setdefault(key, []).append(contact.pk)
    leads = {}
    for lead in Lead.objects.filter(deleted_at__isnull=True):
        key = f"{lead.first_name} {lead.last_name}".strip().casefold()
        leads.setdefault(key, []).append(lead.pk)
    pending = Activity.objects.exclude(with_whom="").filter(
        with_contact__isnull=True,
        with_lead__isnull=True,
    )
    for activity in pending:
        key = activity.with_whom.strip().casefold()
        contact_ids = contacts.get(key, [])
        lead_ids = leads.get(key, [])
        if len(contact_ids) == 1 and not lead_ids:
            activity.with_contact_id = contact_ids[0]
            activity.save(update_fields=["with_contact"])
        elif len(lead_ids) == 1 and not contact_ids:
            activity.with_lead_id = lead_ids[0]
            activity.save(update_fields=["with_lead"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_contact_email_required"),
        ("leads", "0010_lead_email_required"),
        ("activities", "0003_activity_with_whom"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="with_contact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="activities_with",
                to="accounts.contact",
            ),
        ),
        migrations.AddField(
            model_name="activity",
            name="with_lead",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="activities_with",
                to="leads.lead",
            ),
        ),
        migrations.AddConstraint(
            model_name="activity",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("with_contact__isnull", False),
                    ("with_lead__isnull", False),
                    _negated=True,
                ),
                name="activities_activity_one_party",
            ),
        ),
        migrations.RunPython(link_saved_names, migrations.RunPython.noop),
    ]
