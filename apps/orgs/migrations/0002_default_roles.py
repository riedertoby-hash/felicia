from django.db import migrations


def seed_roles(apps, schema_editor):
    from apps.orgs.permissions import DEFAULT_ROLES

    Role = apps.get_model("orgs", "Role")
    for key, kind, name, description, permissions, is_owner, sort in DEFAULT_ROLES:
        Role.objects.update_or_create(
            tenant=None, key=key,
            defaults={"kind": kind, "name": name, "description": description, "permissions": permissions,
                      "is_owner": is_owner, "sort": sort},
        )


class Migration(migrations.Migration):
    dependencies = [("orgs", "0001_initial")]
    operations = [migrations.RunPython(seed_roles, migrations.RunPython.noop)]
