from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0007_open_list_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="budget_range",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="buying_timeline",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="current_tools",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="demo_scheduled_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="technical_contact_name",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
