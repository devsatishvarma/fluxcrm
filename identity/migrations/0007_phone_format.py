import re

from django.db import migrations


def _format(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def format_user_phones(apps, schema_editor):
    user_model = apps.get_model("identity", "User")
    for user in user_model.objects.all().only("pk", "phone"):
        formatted = _format(user.phone)
        if formatted and formatted != user.phone:
            user_model.objects.filter(pk=user.pk).update(phone=formatted)


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0006_user_phone"),
    ]

    operations = [
        migrations.RunPython(format_user_phones, migrations.RunPython.noop),
    ]
