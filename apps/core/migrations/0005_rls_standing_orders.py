from django.db import migrations

POLICIES = {
    "orders_standingorder": "customer_id = felicia_org() OR supplier_id = felicia_org() "
                            "OR felicia_operator_tenant() IS NOT NULL",
    "orders_standingorderitem": "EXISTS (SELECT 1 FROM orders_standingorder s WHERE s.id = standing_order_id)",
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
    dependencies = [("core", "0004_rls_payments"), ("orders", "0002_standingorder_standingorderitem")]
    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
