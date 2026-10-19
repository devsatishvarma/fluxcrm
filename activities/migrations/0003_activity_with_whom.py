from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0002_task_hold_and_list_sort"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="with_whom",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
