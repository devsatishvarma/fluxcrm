from django.db import migrations


def demote_app_administrators(apps, schema_editor):
    user = apps.get_model("identity", "User")
    user.objects.filter(role__key="ADMIN").update(
        is_staff=False,
        is_superuser=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0002_alter_user_manager"),
    ]

    operations = [
        migrations.RunPython(
            demote_app_administrators,
            migrations.RunPython.noop,
        ),
    ]
