from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_contact_phones"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="address",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="contact",
            name="address",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
