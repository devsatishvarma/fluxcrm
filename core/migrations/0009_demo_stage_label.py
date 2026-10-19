from django.db import migrations


def rename_demo_stage(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    picklist.objects.filter(list_key="LEAD_STAGE", key="DEMO_POC").update(label="Demo")


def restore_demo_stage(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    picklist.objects.filter(list_key="LEAD_STAGE", key="DEMO_POC").update(
        label="Demo/POC Scheduled"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_deal_stages"),
    ]

    operations = [
        migrations.RunPython(rename_demo_stage, restore_demo_stage),
    ]
