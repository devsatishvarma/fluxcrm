from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0003_lead_temperature"),
    ]

    operations = [
        migrations.RenameField(
            model_name="lead",
            old_name="temperature",
            new_name="rating",
        ),
    ]
