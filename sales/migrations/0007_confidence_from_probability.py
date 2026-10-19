from decimal import Decimal

from django.db import migrations


def sync_confidence(apps, schema_editor):
    Deal = apps.get_model("sales", "Deal")
    Deal.objects.filter(probability__gte=Decimal("80")).update(confidence="HIGH")
    Deal.objects.filter(
        probability__gte=Decimal("40"), probability__lt=Decimal("80")
    ).update(confidence="MEDIUM")
    Deal.objects.filter(probability__lt=Decimal("40")).update(confidence="LOW")


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0006_task_hold_and_list_sort"),
    ]

    operations = [
        migrations.RunPython(sync_confidence, migrations.RunPython.noop),
    ]
