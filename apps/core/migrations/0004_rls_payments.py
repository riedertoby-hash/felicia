from django.db import migrations

POLICIES = {
    "billing_reminder": "EXISTS (SELECT 1 FROM billing_invoice i WHERE i.id = invoice_id)",
    "billing_payment": "organization_id = felicia_org() OR felicia_operator_tenant() IS NOT NULL",
}

FORWARD = "\n".join(
    f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;"
    f"CREATE POLICY felicia_scope ON {t} USING (felicia_unrestricted() OR {rule}) "
    f"WITH CHECK (felicia_unrestricted() OR {rule});"
    for t, rule in POLICIES.items()
)
BACKWARD = "\n".join(
    f"DROP POLICY IF EXISTS felicia_scope ON {t}; ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY;"
    f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;"
    for t in POLICIES
)


class Migration(migrations.Migration):
    dependencies = [("core", "0003_row_level_security"), ("billing", "0003_billingsettings_first_reminder_days_and_more")]
    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
