import re

from django.db import migrations


def _format(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def format_lead_phones(apps, schema_editor):
    lead_model = apps.get_model("leads", "Lead")
    for lead in lead_model.objects.all().only("pk", "work_phone", "mobile_phone"):
        updates = {}
        for field in ("work_phone", "mobile_phone"):
            formatted = _format(getattr(lead, field))
            if formatted and formatted != getattr(lead, field):
                updates[field] = formatted
        if updates:
            lead_model.objects.filter(pk=lead.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0008_lead_stage_fields"),
    ]

    operations = [
        migrations.RunPython(format_lead_phones, migrations.RunPython.noop),
    ]
