"""Remove the placeholder Technical Presales team once its members have a home."""

from django.db import migrations

HOMES = {
    "MARKETING": "Marketing",
    "SALES_DIRECTOR": "Sales",
    "SALES_EXECUTIVE": "Technical Pre-Sales",
    "CLIENT_SUCCESS": "Technical Pre-Sales",
    "STANDARD_USER": "Sales",
    "READ_ONLY": "Executive Management",
}


def remove_placeholder_team(apps, schema_editor):
    Team = apps.get_model("identity", "Team")
    User = apps.get_model("identity", "User")
    placeholder = Team.objects.filter(name="Technical Presales").first()
    if placeholder is None:
        return
    for user in User.objects.filter(team=placeholder).select_related("role"):
        role_key = user.role.key if user.role_id else ""
        home = (
            Team.objects.filter(name=HOMES.get(role_key, ""))
            .exclude(pk=placeholder.pk)
            .first()
        )
        if home is None:
            continue
        user.team = home
        user.save(update_fields=("team",))
        user.teams.set([home])
    placeholder.members.clear()
    if User.objects.filter(team=placeholder).exists():
        return
    placeholder.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0008_version2_access"),
    ]

    operations = [
        migrations.RunPython(remove_placeholder_team, migrations.RunPython.noop),
    ]
