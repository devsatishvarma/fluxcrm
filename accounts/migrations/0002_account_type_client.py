from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="account_type",
            field=models.CharField(
                choices=[
                    ("CUSTOMER", "Customer"),
                    ("CLIENT", "Client"),
                    ("PROSPECT", "Prospect"),
                    ("PARTNER", "Partner"),
                    ("REFERRAL", "Referral"),
                    ("COMPETITOR", "Competitor"),
                    ("OEM_VENDOR", "OEM Vendor"),
                    ("OTHER", "Other"),
                ],
                max_length=32,
            ),
        ),
    ]
