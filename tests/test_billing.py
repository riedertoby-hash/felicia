from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing import services
from apps.billing.models import BillingSettings, CustomerTerms, Invoice
from apps.billing.reference import creditor_reference, is_valid
from apps.operator.models import MarketplaceSettings
from apps.orders.models import Order
from tests.test_orders import add, address, checkout, setup_supplier, tomorrow  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def delivered(login, customer, supplier_a, address):  # noqa: F811
    """Two delivered orders of the customer at supplier A (VAT-registered, with IBAN)."""
    profile = supplier_a.supplier_profile
    profile.vat_registered, profile.vat_number = True, "CHE-123.456.788 MWST"
    profile.iban, profile.street, profile.zip_code, profile.city = "CH9300762011623852957", "Hof 1", "4410", "Liestal"
    profile.save()
    option, _, variant = setup_supplier(supplier_a, price="10.25")
    client = login(customer.owner)
    orders = []
    for _ in range(2):
        add(client, variant, 6)
        checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
        orders.append(Order.objects.latest("pk"))
    Order.objects.update(status="delivered")
    return orders


def set_mode(org, mode):
    s = BillingSettings.for_org(org)
    s.invoice_mode = mode
    s.save()


def test_creditor_reference():
    ref = creditor_reference("12X2026-0001")
    assert ref.startswith("RF") and is_valid(ref)
    assert not is_valid(ref[:-1] + ("0" if ref[-1] != "0" else "1"))


def test_periods():
    assert services.last_closed_period("monthly", date(2026, 11, 1)) == (date(2026, 10, 1), date(2026, 10, 31))
    assert services.last_closed_period("quarterly", date(2026, 11, 15)) == (date(2026, 7, 1), date(2026, 9, 30))
    assert services.last_closed_period("quarterly", date(2027, 1, 2)) == (date(2026, 10, 1), date(2026, 12, 31))


def test_monthly_collective_invoice(supplier_a, customer, delivered):
    set_mode(supplier_a, "monthly")
    day = delivered[0].delivery_date
    assert services.run_periodic_invoicing(today=day) == []  # month not closed yet
    next_month = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    invoices = services.run_periodic_invoicing(today=next_month)
    assert len(invoices) == 1
    invoice = invoices[0]
    # 2 × (6 × 10.25 = 61.50 + fee 8.00)
    assert invoice.total == Decimal("139.00")
    assert invoice.issuer == supplier_a and invoice.recipient == customer
    assert set(Order.objects.values_list("invoice", flat=True)) == {invoice.pk}
    # VAT 2.6 % is contained in the gross amount
    assert invoice.vat_breakdown == [["2.6", "135.48", "3.52"]]
    assert services.run_periodic_invoicing(today=next_month) == []  # idempotent


def test_quarterly_and_manual_modes(supplier_a, customer, delivered):
    set_mode(supplier_a, "manual")
    far = timezone.localdate() + timedelta(days=200)
    assert services.run_periodic_invoicing(today=far) == []
    CustomerTerms.objects.create(
        supplier=supplier_a, customer=customer, invoice_mode="quarterly", payment_terms_days=60
    )
    invoices = services.run_periodic_invoicing(today=far)
    assert len(invoices) == 1
    assert invoices[0].due_date == invoices[0].issue_date + timedelta(days=60)


def test_per_order_invoice_on_delivery(login, supplier_a, customer, address):  # noqa: F811
    set_mode(supplier_a, "per_order")
    option, _, variant = setup_supplier(supplier_a)
    client = login(customer.owner)
    add(client, variant, 6)
    checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
    order = Order.objects.get()
    s = login(supplier_a.owner)
    for status in ("confirmed", "delivered"):
        s.post(reverse("supplier_orders:set_status", args=[order.pk]), {"status": status})
    order.refresh_from_db()
    assert order.invoice is not None and order.invoice.total == order.total


def test_manual_invoice_paid_and_cancel(login, supplier_a, customer, delivered):
    client = login(supplier_a.owner)
    client.post(reverse("billing:create_invoice", args=[customer.pk]))
    invoice = Invoice.objects.get()
    client.post(reverse("billing:paid", args=[invoice.pk]), {"paid": "1"})
    invoice.refresh_from_db()
    assert invoice.status == "paid" and invoice.paid_at == timezone.localdate()
    client.post(reverse("billing:cancel", args=[invoice.pk]))
    invoice.refresh_from_db()
    assert invoice.status == "paid"  # paid invoices cannot be cancelled
    client.post(reverse("billing:paid", args=[invoice.pk]), {"paid": "0"})
    client.post(reverse("billing:cancel", args=[invoice.pk]))
    invoice.refresh_from_db()
    assert invoice.status == "cancelled"
    assert not Order.objects.filter(invoice__isnull=False).exists()  # orders are invoiceable again


def test_invoice_pdf_has_qr_bill_and_access_is_limited(login, supplier_a, supplier_b, customer, delivered, tenant):
    from apps.orgs.services import create_organization
    from tests.conftest import make_user

    invoice = services.create_sale_invoice(supplier=supplier_a, customer=customer, orders=delivered)
    url = reverse("billing:pdf", args=[invoice.pk])
    response = login(customer.owner).get(url)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert login(supplier_a.owner).get(url).status_code == 200
    assert login(supplier_b.owner).get(url).status_code == 404
    other = create_organization(tenant=tenant, kind="customer", name="Bären", owner=make_user("chef@baeren.ch"))
    assert login(other.memberships.get().user).get(url).status_code == 404
    assert login(customer.buyer).get(url).status_code == 403  # no finance.view
    # customer cannot mark its own invoice as paid
    login(customer.owner).post(reverse("billing:paid", args=[invoice.pk]), {"paid": "1"})
    invoice.refresh_from_db()
    assert invoice.status == "open"


def test_clerk_cannot_create_invoices(login, supplier_a, customer, delivered):
    assert login(supplier_a.clerk).post(reverse("billing:create_invoice", args=[customer.pk])).status_code == 403
    assert login(supplier_a.readonly).get(reverse("billing:supplier_invoices")).status_code == 200
    assert login(supplier_a.readonly).post(reverse("billing:create_invoice", args=[customer.pk])).status_code == 403


def test_commission_invoice(operator, supplier_a, delivered):
    settings = MarketplaceSettings.for_tenant(supplier_a.tenant)
    settings.vat_registered, settings.base_fee_enabled, settings.base_fee_monthly = True, True, Decimal("20")
    settings.save()
    day = delivered[0].delivery_date
    period = (day.replace(day=1), services.month_bounds(day)[1])
    invoice = services.create_commission_invoice(supplier=supplier_a, period=period)
    # commission 15 % of goods 2 × 61.50 = 18.45, plus base fee 20.00
    assert invoice.total == Decimal("38.45")
    assert invoice.issuer == operator and invoice.recipient == supplier_a
    assert invoice.vat_breakdown[0][0] == "8.1"
    assert services.create_commission_invoice(supplier=supplier_a, period=period) is None  # once per period


def test_supplier_cannot_use_operator_billing(login, supplier_a, operator):
    client = login(supplier_a.owner)
    assert client.get(reverse("billing:operator_invoices")).status_code == 403
    assert client.post(reverse("billing:operator_run")).status_code == 403
    assert login(operator.staff).get(reverse("billing:operator_invoices")).status_code == 403


def test_run_billing_command(supplier_a, delivered):
    from django.core.management import call_command

    set_mode(supplier_a, "monthly")
    call_command("run_billing")  # must not fail even when nothing is due
