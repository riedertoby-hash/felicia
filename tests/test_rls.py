"""The database itself must hide other organizations' orders and invoices, even for unfiltered queries."""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.billing import services as billing
from apps.billing.models import Invoice, InvoiceLine
from apps.core.rls import acting_as
from apps.customers.models import Address
from apps.orders.models import CartItem, Order, OrderLine
from apps.orgs.services import create_organization
from tests.conftest import make_user
from tests.test_orders import add, address, checkout, setup_supplier, tomorrow  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_orders(login, tenant, customer, supplier_a, supplier_b, address):  # noqa: F811
    """customer orders at A and B; a second customer orders at A."""
    option_a, _, variant_a = setup_supplier(supplier_a)
    option_b, _, variant_b = setup_supplier(supplier_b, name="Käse")
    client = login(customer.owner)
    add(client, variant_a, 6)
    add(client, variant_b, 6)
    checkout(client, address, {supplier_a.pk: (option_a.pk, tomorrow()), supplier_b.pk: (option_b.pk, tomorrow())})
    other = create_organization(tenant=tenant, kind="customer", name="Bären", owner=make_user("chef@baeren.ch"))
    other_address = Address.objects.create(
        organization=other, label="K", recipient="Bären", street="Weg 1", zip_code="4052", city="Basel", canton="BS"
    )
    other_client = login(other.memberships.get().user)
    add(other_client, variant_a, 6)
    checkout(other_client, other_address, {supplier_a.pk: (option_a.pk, tomorrow())})
    Order.objects.update(status="delivered")
    for order in Order.objects.all():
        billing.create_sale_invoice(supplier=order.supplier, customer=order.customer, orders=[order])
    return other


def test_db_requires_non_superuser():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone()[0] is False, "Tests must run as a normal role, otherwise RLS is not tested"


def test_without_request_context_everything_is_visible(two_orders):
    assert Order.objects.count() == 3 and Invoice.objects.count() == 3


def test_customer_sees_only_own_rows(customer, two_orders):
    with acting_as(customer):
        assert set(Order.objects.values_list("customer", flat=True)) == {customer.pk}
        assert Order.objects.count() == 2
        assert set(Invoice.objects.values_list("recipient", flat=True)) == {customer.pk}
        assert OrderLine.objects.count() == 2
        assert not InvoiceLine.objects.exclude(invoice__recipient=customer).exists()
        assert not Address.objects.exclude(organization=customer).exists()


def test_supplier_sees_only_orders_to_itself(supplier_a, supplier_b, two_orders):
    with acting_as(supplier_b):
        assert Order.objects.count() == 1 and Invoice.objects.count() == 1
        assert not Address.objects.exists()
    with acting_as(supplier_a):
        assert Order.objects.count() == 2


def test_operator_sees_all_of_its_marketplace(operator, two_orders):
    with acting_as(operator):
        assert Order.objects.count() == 3 and Invoice.objects.count() == 3


def test_writes_for_other_organizations_are_rejected(customer, supplier_a, two_orders):
    foreign = Order.objects.get(customer=two_orders)
    foreign_variant = foreign.lines.first().variant
    with acting_as(customer):
        assert foreign.lines.first() is None  # lines of foreign orders are invisible too
        # update of an invisible row silently affects nothing
        assert Order.objects.filter(pk=foreign.pk).update(status="cancelled") == 0
        # inserting a row for another customer is refused by the database
        with pytest.raises(DatabaseError), transaction.atomic():
            CartItem.objects.create(customer=two_orders, user=customer.owner, variant=foreign_variant, quantity=2)
    foreign.refresh_from_db()
    assert foreign.status == "delivered"


def test_anonymous_request_context_sees_nothing(two_orders):
    with acting_as(None):
        assert Order.objects.count() == 0 and Invoice.objects.count() == 0


def test_context_is_reset_after_each_request(client, customer, two_orders):
    client.force_login(customer.owner)
    client.get("/kunde/bestellungen/")
    assert Order.objects.count() == 3  # back to system context after the request
