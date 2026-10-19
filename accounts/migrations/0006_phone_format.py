import re

from django.db import migrations


def _format(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def format_account_phones(apps, schema_editor):
    account_model = apps.get_model("accounts", "Account")
    contact_model = apps.get_model("accounts", "Contact")
    for account in account_model.objects.all().only("pk", "phone"):
        formatted = _format(account.phone)
        if formatted and formatted != account.phone:
            account_model.objects.filter(pk=account.pk).update(phone=formatted)
    for contact in contact_model.objects.all().only("pk", "work_phone", "mobile_phone"):
        updates = {}
        for field in ("work_phone", "mobile_phone"):
            formatted = _format(getattr(contact, field))
            if formatted and formatted != getattr(contact, field):
                updates[field] = formatted
        if updates:
            contact_model.objects.filter(pk=contact.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_address"),
    ]

    operations = [
        migrations.RunPython(format_account_phones, migrations.RunPython.noop),
    ]
