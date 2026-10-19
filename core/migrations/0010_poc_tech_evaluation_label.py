from django.db import migrations


def rename_evaluation_stage(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    picklist.objects.filter(list_key="DEAL_STAGE", key="TECHNICAL_EVALUATION").update(
        label="POC/Tech Evaluation"
    )


def restore_evaluation_stage(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    picklist.objects.filter(list_key="DEAL_STAGE", key="TECHNICAL_EVALUATION").update(
        label="Technical Evaluation"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_demo_stage_label"),
    ]

    operations = [
        migrations.RunPython(rename_evaluation_stage, restore_evaluation_stage),
    ]
