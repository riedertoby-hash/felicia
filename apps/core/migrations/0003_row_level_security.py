"""Second barrier in the database: row-level security on organization-owned business data."""

from django.db import migrations

FUNCTIONS = """
CREATE OR REPLACE FUNCTION felicia_unrestricted() RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('app.mode', true), '') <> 'request' $$;
CREATE OR REPLACE FUNCTION felicia_org() RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.org_id', true), '')::bigint $$;
CREATE OR REPLACE FUNCTION felicia_operator_tenant() RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN current_setting('app.org_kind', true) = 'operator'
              THEN nullif(current_setting('app.tenant_id', true), '')::bigint END $$;
"""

POLICIES = {
    "orders_order": "customer_id = felicia_org() OR supplier_id = felicia_org() "
                    "OR tenant_id = felicia_operator_tenant()",
    "orders_orderline": "EXISTS (SELECT 1 FROM orders_order o WHERE o.id = order_id)",
    "orders_cartitem": "customer_id = felicia_org()",
    "billing_invoice": "issuer_id = felicia_org() OR recipient_id = felicia_org() "
                       "OR tenant_id = felicia_operator_tenant()",
    "billing_invoiceline": "EXISTS (SELECT 1 FROM billing_invoice i WHERE i.id = invoice_id)",
    "billing_billingsettings": "organization_id = felicia_org() OR felicia_operator_tenant() IS NOT NULL",
    "billing_customerterms": "supplier_id = felicia_org() OR felicia_operator_tenant() IS NOT NULL",
    "customers_address": "organization_id = felicia_org() OR felicia_operator_tenant() IS NOT NULL",
}


def forward_sql():
    parts = [FUNCTIONS]
    for table, rule in POLICIES.items():
        parts.append(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"
            f"CREATE POLICY felicia_scope ON {table} USING (felicia_unrestricted() OR {rule}) "
            f"WITH CHECK (felicia_unrestricted() OR {rule});"
        )
    return "\n".join(parts)


def backward_sql():
    parts = []
    for table in POLICIES:
        parts.append(
            f"DROP POLICY IF EXISTS felicia_scope ON {table};"
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;"
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"
        )
    parts.append("DROP FUNCTION IF EXISTS felicia_unrestricted(); DROP FUNCTION IF EXISTS felicia_org();"
                 "DROP FUNCTION IF EXISTS felicia_operator_tenant();")
    return "\n".join(parts)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_sequence"),
        ("orders", "0001_initial"),
        ("billing", "0002_initial"),
        ("customers", "0002_address_canton"),
    ]
    operations = [migrations.RunSQL(forward_sql(), backward_sql())]
