from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0004_activity_party"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminder",
            name="email_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the Graph reminder email was sent; null until delivered.",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(
                fields=["email_sent_at"],
                name="activities_rem_email_sent_idx",
            ),
        ),
    ]
