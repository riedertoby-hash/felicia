from django.db import migrations


def add_permission(apps, schema_editor):
    Role = apps.get_model("orgs", "Role")
    for key in ("supplier_owner", "supplier_admin", "operator_admin"):
        role = Role.objects.filter(tenant=None, key=key).first()
        if role and "finance.manage" not in role.permissions:
            role.permissions = [*role.permissions, "finance.manage"]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("orgs", "0002_default_roles")]
    operations = [migrations.RunPython(add_permission, migrations.RunPython.noop)]
