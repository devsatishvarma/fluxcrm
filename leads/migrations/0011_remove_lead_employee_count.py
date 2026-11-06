from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0010_lead_email_required"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="lead",
            name="employee_count",
        ),
    ]
