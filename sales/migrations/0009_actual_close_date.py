from datetime import UTC
from zoneinfo import ZoneInfo

from django.db import migrations, models
from django.utils import timezone


def backfill_actual_close_dates(apps, schema_editor):
    """Give existing wins the day the stage moved, so that date can be corrected."""
    Deal = apps.get_model("sales", "Deal")
    History = apps.get_model("core", "StageHistory")
    zone = ZoneInfo("America/Los_Angeles")
    for deal in Deal.objects.filter(outcome="WON").iterator():
        row = (
            History.objects.filter(
                object_type="deal",
                object_id=deal.pk,
                to_stage="CLOSED_WON",
            )
            .order_by("-changed_at")
            .first()
        )
        moment = deal.stage_entered_at if row is None else row.changed_at
        if moment is None:
            continue
        if timezone.is_naive(moment):
            moment = moment.replace(tzinfo=UTC)
        Deal.objects.filter(pk=deal.pk).update(
            actual_close_date=moment.astimezone(zone).date()
        )


def clear_actual_close_dates(apps, schema_editor):
    Deal = apps.get_model("sales", "Deal")
    Deal.objects.update(actual_close_date=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_poc_tech_evaluation_label"),
        ("sales", "0008_deal_evaluation_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="deal",
            name="actual_close_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_actual_close_dates, clear_actual_close_dates),
    ]
