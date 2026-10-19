from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0007_confidence_from_probability"),
    ]

    operations = [
        migrations.AddField(
            model_name="deal",
            name="evaluation_started_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deal",
            name="technical_stakeholder_name",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
