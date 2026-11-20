"""Limit stored audit grants to each person's own actions."""

from django.db import migrations

FULL_AUDIT_ROLES = {"ADMIN", "SUPER_ADMIN"}


def narrow_audit(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    for role in Role.objects.exclude(key__in=FULL_AUDIT_ROLES):
        permissions = dict(role.permissions or {})
        objects = dict(permissions.get("objects") or {})
        audit = dict(objects.get("audit") or {})
        if "scopes" in audit or permissions.get("version") == 2:
            scopes = dict(audit.get("scopes") or {})
            if scopes == {"R": "OWN"}:
                continue
            audit["scopes"] = {"R": "OWN"}
            audit.pop("actions", None)
            audit.pop("scope", None)
        else:
            if audit.get("actions") == "R" and audit.get("scope") == "OWN":
                continue
            audit["actions"] = "R"
            audit["scope"] = "OWN"
        objects["audit"] = audit
        permissions["objects"] = objects
        role.permissions = permissions
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0009_remove_placeholder_team"),
    ]

    operations = [
        migrations.RunPython(narrow_audit, migrations.RunPython.noop),
    ]
