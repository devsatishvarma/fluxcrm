"""Version 2.0 roles and one team per user."""

from django.db import migrations, models


def upgrade_access(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    User = apps.get_model("identity", "User")
    Team = apps.get_model("identity", "Team")

    sales = Role.objects.filter(key="SALES_EXECUTIVE").first()
    account_executive = Role.objects.filter(key="ACCOUNT_EXECUTIVE").first()
    if account_executive and sales is None:
        account_executive.key = "SALES_EXECUTIVE"
        account_executive.name = "Sales Executive"
        account_executive.save(update_fields=("key", "name"))
        sales = account_executive
    elif account_executive and sales is not None:
        User.objects.filter(role=account_executive).update(role=sales)
        account_executive.delete()

    sdr = Role.objects.filter(key="SDR").first()
    if sdr is not None:
        if sales is None:
            sales = Role.objects.create(
                key="SALES_EXECUTIVE",
                name="Sales Executive",
                description="Own leads, deals, tasks, and activities.",
                permissions={"version": 0},
                scope_policy="OWN",
            )
        User.objects.filter(role=sdr).update(role=sales)
        sdr.delete()

    super_admin = Role.objects.filter(key="SUPER_ADMIN").first()
    if super_admin is None:
        super_admin = Role.objects.create(
            key="SUPER_ADMIN",
            name="Super Admin",
            description="Creates users, sets passwords, and can change every record.",
            permissions={"version": 0},
            scope_policy="ALL",
        )
    first_admin = User.objects.filter(role__key="ADMIN").order_by("pk").first()
    if first_admin is not None:
        first_admin.role = super_admin
        first_admin.save(update_fields=("role",))

    presales, _created = Team.objects.get_or_create(
        name="Technical Presales",
        defaults={"active": True},
    )
    membership = User.teams.through
    for user in User.objects.select_related("role"):
        key = user.role.key if user.role_id else ""
        if key in {"ADMIN", "SUPER_ADMIN"}:
            user.team = None
        else:
            team_ids = list(
                membership.objects.filter(user_id=user.pk).values_list(
                    "team_id", flat=True
                )
            )
            active = list(
                Team.objects.filter(pk__in=team_ids, active=True).order_by("name")
            )
            user.team = active[0] if active else presales
        user.save(update_fields=("team",))

    from core.services import ensure_roles

    ensure_roles()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0007_phone_format"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="assigned_users",
                to="identity.team",
            ),
        ),
        migrations.RunPython(upgrade_access, migrations.RunPython.noop),
    ]
