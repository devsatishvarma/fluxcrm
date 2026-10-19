from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0009_phone_format"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="email",
            field=models.EmailField(max_length=254),
        ),
    ]
