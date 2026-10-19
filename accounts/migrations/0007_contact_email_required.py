from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_phone_format"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contact",
            name="email",
            field=models.EmailField(max_length=254),
        ),
    ]
