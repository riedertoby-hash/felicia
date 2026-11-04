"""Row-level security: the database itself restricts orders, invoices, carts and addresses to the
organization a request acts for. This is a second barrier behind the filters in the views.

Inside a web request the context is «request» with the active organization; outside requests
(management commands, scheduled jobs, migrations) no context is set and the policies allow all rows.
"""

from contextlib import contextmanager

from django.db import connection

PROTECTED_TABLES = [
    "orders_standingorder",
    "orders_standingorderitem",
    "billing_reminder",
    "billing_payment",
    "orders_order",
    "orders_orderline",
    "orders_cartitem",
    "billing_invoice",
    "billing_invoiceline",
    "billing_billingsettings",
    "billing_customerterms",
    "customers_address",
]


def set_request_context(org=None, tenant=None):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.mode', 'request', false), set_config('app.org_id', %s, false), "
            "set_config('app.org_kind', %s, false), set_config('app.tenant_id', %s, false)",
            [str(org.pk) if org else "", org.kind if org else "", str(tenant.pk) if tenant else ""],
        )


def clear_context():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.mode', '', false), set_config('app.org_id', '', false), "
            "set_config('app.org_kind', '', false), set_config('app.tenant_id', '', false)"
        )


@contextmanager
def acting_as(org):
    """For tests and rare system tasks: run queries as if a request for `org` were active."""
    set_request_context(org, getattr(org, "tenant", None))
    try:
        yield
    finally:
        clear_context()


class RowLevelSecurityMiddleware:
    """Must come after OrganizationMiddleware (needs request.org)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "tenant", None) is None:
            return self.get_response(request)
        set_request_context(getattr(request, "org", None), request.tenant)
        try:
            return self.get_response(request)
        finally:
            clear_context()
