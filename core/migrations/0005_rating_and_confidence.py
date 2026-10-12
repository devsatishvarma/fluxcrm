from django.db import migrations


def split_temperature_lists(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    picklist.objects.filter(list_key="TEMPERATURE").update(active=False)
    rows = (
        ("LEAD_RATING", "HOT", "Hot", 1),
        ("LEAD_RATING", "WARM", "Warm", 2),
        ("LEAD_RATING", "COLD", "Cold", 3),
        ("DEAL_CONFIDENCE", "HIGH", "High", 1),
        ("DEAL_CONFIDENCE", "MEDIUM", "Medium", 2),
        ("DEAL_CONFIDENCE", "LOW", "Low", 3),
    )
    for list_key, key, label, order in rows:
        picklist.objects.get_or_create(
            list_key=list_key,
            key=key,
            defaults={"label": label, "order": order, "active": True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_audit_hardening"),
    ]

    operations = [
        migrations.RunPython(split_temperature_lists, migrations.RunPython.noop),
    ]
