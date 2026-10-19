from django.db import migrations

INDUSTRIES = (
    ("INFORMATION_TECHNOLOGY", "Information Technology"),
    ("TECHNOLOGY_SAAS", "Technology & SaaS"),
    ("PROFESSIONAL_SERVICES", "Professional Services"),
    ("HEALTHCARE", "Healthcare"),
    ("FINANCIAL_SERVICES", "Financial Services"),
    ("INSURANCE", "Insurance"),
    ("MANUFACTURING", "Manufacturing"),
    ("AUTOMOTIVE", "Automotive"),
    ("RETAIL", "Retail & E-Commerce"),
    ("HOSPITALITY_TRAVEL", "Hospitality & Travel"),
    ("EDUCATION", "Education"),
    ("GOVERNMENT", "Government"),
    ("NONPROFIT", "Nonprofit"),
    ("OTHER", "Other"),
)


def sync_industries(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    for order, (key, label) in enumerate(INDUSTRIES, start=1):
        row, _created = picklist.objects.get_or_create(
            list_key="INDUSTRY",
            key=key,
            defaults={"label": label, "order": order, "active": True},
        )
        row.label = label
        row.order = order
        row.save(update_fields=["label", "order"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_rating_and_confidence"),
    ]

    operations = [
        migrations.RunPython(sync_industries, migrations.RunPython.noop),
    ]
