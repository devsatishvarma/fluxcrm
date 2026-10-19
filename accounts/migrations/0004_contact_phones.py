from django.db import migrations, models


def copy_blank_phones_from_lead(apps, schema_editor):
    contact_model = apps.get_model("accounts", "Contact")
    lead_model = apps.get_model("leads", "Lead")
    leads = {
        lead.pk: lead
        for lead in lead_model.objects.all().only("pk", "work_phone", "mobile_phone")
    }
    for contact in contact_model.objects.exclude(converted_from_lead_id=None):
        lead = leads.get(contact.converted_from_lead_id)
        if lead is None:
            continue
        updates = []
        work = str(lead.work_phone or "").strip()[:40]
        mobile = str(lead.mobile_phone or "").strip()[:40]
        if not contact.work_phone and work:
            contact.work_phone = work
            updates.append("work_phone")
        if not contact.mobile_phone and mobile:
            contact.mobile_phone = mobile
            updates.append("mobile_phone")
        if updates:
            contact.save(update_fields=updates)


def clear_copied_phones(apps, schema_editor):
    contact_model = apps.get_model("accounts", "Contact")
    lead_model = apps.get_model("leads", "Lead")
    leads = {lead.pk: lead for lead in lead_model.objects.all()}
    for contact in contact_model.objects.exclude(converted_from_lead_id=None):
        lead = leads.get(contact.converted_from_lead_id)
        if lead is None:
            continue
        updates = []
        work = str(lead.work_phone or "").strip()[:40]
        mobile = str(lead.mobile_phone or "").strip()[:40]
        if work and contact.work_phone == work:
            contact.work_phone = ""
            updates.append("work_phone")
        if mobile and contact.mobile_phone == mobile:
            contact.mobile_phone = ""
            updates.append("mobile_phone")
        if updates:
            contact.save(update_fields=updates)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_merge_client_into_customer"),
        ("leads", "0008_lead_stage_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="work_phone",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="contact",
            name="mobile_phone",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.RunPython(copy_blank_phones_from_lead, clear_copied_phones),
    ]
