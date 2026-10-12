from django.db import migrations

CONFIDENCE_FROM_TEMPERATURE = {
    "HOT": "HIGH",
    "WARM": "MEDIUM",
    "COLD": "LOW",
}


def map_confidence(apps, schema_editor):
    deal = apps.get_model("sales", "Deal")
    for old, new in CONFIDENCE_FROM_TEMPERATURE.items():
        deal.objects.filter(confidence=old).update(confidence=new)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0003_audit_hardening"),
    ]

    operations = [
        migrations.RenameField(
            model_name="deal",
            old_name="temperature",
            new_name="confidence",
        ),
        migrations.RunPython(map_confidence, migrations.RunPython.noop),
    ]
