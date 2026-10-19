from django.db import migrations, models


def merge_client_into_customer(apps, schema_editor):
    account = apps.get_model("accounts", "Account")
    account.objects.filter(account_type="CLIENT").update(account_type="CUSTOMER")
    import_row = apps.get_model("imports", "ImportRow")
    for row in import_row.objects.exclude(before_json=None).iterator():
        before = row.before_json
        if isinstance(before, dict) and before.get("account_type") == "CLIENT":
            before["account_type"] = "CUSTOMER"
            row.before_json = before
            row.save(update_fields=["before_json"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_account_type_client"),
        ("imports", "0001_csv_batches"),
    ]

    operations = [
        migrations.RunPython(merge_client_into_customer, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="account",
            name="account_type",
            field=models.CharField(
                choices=[
                    ("CUSTOMER", "Customer"),
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
