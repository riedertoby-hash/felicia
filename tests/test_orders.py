from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.catalog.defaults import seed_catalog_defaults
from apps.catalog.models import Category, Product, Variant
from apps.customers.models import Address
from apps.delivery import services as delivery
from apps.delivery.models import DeliveryOption, DeliveryZone, FeeTier, parse_zip_list
from apps.orders.models import CartItem, Order

pytestmark = pytest.mark.django_db
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def setup_supplier(supplier, *, min_order="50", zips="4000-4099", price="10.00", stock=None, name="Kartoffeln"):
    seed_catalog_defaults(supplier.tenant)
    option = DeliveryOption.objects.create(
        supplier=supplier, kind="own", name="Hoflieferung", weekdays=ALL_DAYS, lead_days=1, cutoff_time=time(23, 59)
    )
    zone = DeliveryZone.objects.create(option=option, name="Basel", zip_codes=zips, min_order_value=Decimal(min_order))
    FeeTier.objects.create(zone=zone, from_value=0, fee=Decimal("8.00"))
    FeeTier.objects.create(zone=zone, from_value=100, fee=Decimal("0"))
    product = Product.objects.create(
        tenant=supplier.tenant,
        supplier=supplier,
        name=name,
        category=Category.objects.get(tenant=supplier.tenant, name="Kartoffeln"),
    )
    variant = Variant.objects.create(
        product=product,
        name="2,5 kg",
        customer_price=Decimal(price),
        min_qty=Decimal("2"),
        qty_step=Decimal("1"),
        stock=Decimal(stock) if stock is not None else None,
    )
    return option, zone, variant


@pytest.fixture
def address(customer):
    return Address.objects.create(
        organization=customer,
        label="Küche",
        recipient="Restaurant Linde",
        street="Hauptstrasse 5",
        zip_code="4051",
        city="Basel",
        canton="BS",
        is_default=True,
    )


def add(client, variant, qty):
    return client.post(reverse("orders:add", args=[variant.pk]), {"quantity": str(qty)})


def checkout(client, address, choices):
    data = {"adresse": address.pk if address else "abholung"}
    for supplier_id, (option_id, day) in choices.items():
        data[f"option_{supplier_id}"] = option_id
        data[f"date_{supplier_id}"] = day.isoformat()
    return client.post(reverse("orders:checkout"), data)


def tomorrow():
    return timezone.localdate() + timedelta(days=1)


# --- delivery rules ---------------------------------------------------------------------------------


def test_zip_parsing_and_coverage(supplier_a):
    assert parse_zip_list("4410, 4400-4499;4051") == [(4410, 4410), (4400, 4499), (4051, 4051)]
    with pytest.raises(ValidationError):
        parse_zip_list("44x")
    _, zone, _ = setup_supplier(supplier_a)
    zone.cantons = ["BL"]
    assert zone.covers("4051") and zone.covers("4410", "BL") and not zone.covers("8000", "ZH")


def test_fee_tiers(supplier_a):
    _, zone, _ = setup_supplier(supplier_a)
    assert zone.fee_for(Decimal("40")) == Decimal("8.00")
    assert zone.fee_for(Decimal("100")) == Decimal("0")


def test_dates_respect_weekdays_and_cutoff(supplier_a):
    option, _, _ = setup_supplier(supplier_a)
    option.weekdays = [1]  # Tuesdays
    option.cutoff_time = time(12, 0)
    monday_morning = timezone.make_aware(datetime(2026, 11, 2, 9, 0))
    monday_evening = timezone.make_aware(datetime(2026, 11, 2, 15, 0))
    assert delivery.possible_dates(option, now=monday_morning)[0] == date(2026, 11, 3)
    assert delivery.possible_dates(option, now=monday_evening)[0] == date(2026, 11, 10)
    # a product needing 3 days pushes the first date
    assert delivery.possible_dates(option, product_lead_days=3, now=monday_morning)[0] == date(2026, 11, 10)


def test_supplier_cannot_edit_foreign_delivery(login, supplier_a, supplier_b):
    option, zone, _ = setup_supplier(supplier_b)
    client = login(supplier_a.owner)
    assert client.get(reverse("delivery:option_edit", args=[option.pk])).status_code == 404
    assert client.get(reverse("delivery:zone_edit", args=[option.pk, zone.pk])).status_code == 404
    assert login(supplier_b.clerk).get(reverse("delivery:option_edit", args=[option.pk])).status_code == 403


# --- cart & checkout ------------------------------------------------------------------------------


def test_quantity_rules(login, customer, supplier_a, address):
    _, _, variant = setup_supplier(supplier_a, stock="5")
    client = login(customer.owner)
    add(client, variant, 1)  # below minimum 2
    add(client, variant, Decimal("2.5"))  # not a whole step
    add(client, variant, 6)  # more than stock
    assert not CartItem.objects.exists()
    add(client, variant, 3)
    assert CartItem.objects.get().quantity == 3


def test_checkout_splits_per_supplier_and_notifies(
    login, customer, supplier_a, supplier_b, address, django_capture_on_commit_callbacks
):
    option_a, _, variant_a = setup_supplier(supplier_a, stock="20")
    option_b, _, variant_b = setup_supplier(supplier_b, name="Käse", price="30.00", min_order="0")
    client = login(customer.owner)
    add(client, variant_a, 6)  # 60.00 + fee 8.00
    add(client, variant_b, 4)  # 120.00, free delivery
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        response = checkout(
            client, address, {supplier_a.pk: (option_a.pk, tomorrow()), supplier_b.pk: (option_b.pk, tomorrow())}
        )
    assert response.status_code == 200
    a = Order.objects.get(supplier=supplier_a)
    b = Order.objects.get(supplier=supplier_b)
    assert (a.goods_total, a.delivery_fee, a.total) == (Decimal("60.00"), Decimal("8.00"), Decimal("68.00"))
    assert (b.goods_total, b.delivery_fee, b.total) == (Decimal("120.00"), Decimal("0"), Decimal("120.00"))
    assert a.checkout_id == b.checkout_id and a.ship_zip == "4051"
    assert a.commission_percent == Decimal("15.00")
    assert not CartItem.objects.exists()
    variant_a.refresh_from_db()
    assert variant_a.stock == Decimal("14")
    recipients = {r for m in mail.outbox for r in m.to}
    assert {"owner@hof-a.ch", "owner@hof-b.ch", "chef@restaurant.ch"} <= recipients


def test_minimum_order_value_blocks_checkout(login, customer, supplier_a, address):
    option, _, variant = setup_supplier(supplier_a, min_order="100")
    client = login(customer.owner)
    add(client, variant, 2)
    checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
    assert not Order.objects.exists()
    assert CartItem.objects.exists()


def test_address_outside_zone_and_invalid_date(login, customer, supplier_a, address):
    option, _, variant = setup_supplier(supplier_a, zips="8000-8099")
    client = login(customer.owner)
    add(client, variant, 6)
    checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
    assert not Order.objects.exists()
    # pickup works for any address, but only on a valid date
    pickup = DeliveryOption.objects.create(
        supplier=supplier_a, kind="pickup", name="Hofladen", weekdays=[0], lead_days=1
    )
    not_monday = next(d for d in (tomorrow() + timedelta(days=i) for i in range(7)) if d.weekday() != 0)
    checkout(client, None, {supplier_a.pk: (pickup.pk, not_monday)})
    assert not Order.objects.exists()
    monday = delivery.possible_dates(pickup)[0]
    checkout(client, None, {supplier_a.pk: (pickup.pk, monday)})
    order = Order.objects.get()
    assert order.delivery_kind == "pickup" and order.ship_street == "" and order.delivery_fee == 0


def test_hidden_product_cannot_be_added(login, customer, supplier_a, address):
    _, _, variant = setup_supplier(supplier_a)
    variant.product.is_active = False
    variant.product.save()
    assert add(login(customer.owner), variant, 2).status_code == 404


def test_order_isolation(login, customer, supplier_a, supplier_b, address, tenant):
    from apps.orgs.services import create_organization
    from tests.conftest import make_user

    option, _, variant = setup_supplier(supplier_a)
    client = login(customer.owner)
    add(client, variant, 6)
    checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
    order = Order.objects.get()
    other = create_organization(tenant=tenant, kind="customer", name="Bären", owner=make_user("chef@baeren.ch"))
    other_client = login(other.memberships.get().user)
    assert other_client.get(reverse("orders:detail", args=[order.pk])).status_code == 404
    assert other_client.get(reverse("orders:delivery_note", args=[order.pk])).status_code == 404
    b = login(supplier_b.owner)
    assert b.get(reverse("supplier_orders:detail", args=[order.pk])).status_code == 404
    assert b.post(reverse("supplier_orders:set_status", args=[order.pk]), {"status": "confirmed"}).status_code == 404


def test_buyer_can_order_but_not_see_invoices(login, customer, supplier_a, address):
    option, _, variant = setup_supplier(supplier_a)
    client = login(customer.buyer)
    add(client, variant, 6)
    checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
    assert Order.objects.filter(placed_by=customer.buyer).exists()
    assert client.get(reverse("billing:customer_invoices")).status_code == 403


# --- status workflow ------------------------------------------------------------------------------


@pytest.fixture
def placed_order(login, customer, supplier_a, address):
    option, _, variant = setup_supplier(supplier_a, stock="10")
    client = login(customer.owner)
    add(client, variant, 6)
    checkout(client, address, {supplier_a.pk: (option.pk, tomorrow())})
    return Order.objects.get()


def test_clerk_moves_status_readonly_cannot(login, supplier_a, placed_order):
    url = reverse("supplier_orders:set_status", args=[placed_order.pk])
    assert login(supplier_a.readonly).post(url, {"status": "confirmed"}).status_code == 403
    login(supplier_a.clerk).post(url, {"status": "confirmed"})
    placed_order.refresh_from_db()
    assert placed_order.status == "confirmed"
    login(supplier_a.clerk).post(url, {"status": "new"})  # backwards is not allowed
    placed_order.refresh_from_db()
    assert placed_order.status == "confirmed"


def test_cancel_restores_stock(login, supplier_a, placed_order):
    variant = placed_order.lines.get().variant
    variant.refresh_from_db()
    assert variant.stock == Decimal("4")
    login(supplier_a.owner).post(reverse("supplier_orders:set_status", args=[placed_order.pk]), {"status": "cancelled"})
    variant.refresh_from_db()
    assert variant.stock == Decimal("10")


def test_reorder_fills_cart(login, customer, placed_order):
    Variant.objects.update(stock=None)
    login(customer.owner).post(reverse("orders:reorder", args=[placed_order.pk]))
    assert CartItem.objects.get().quantity == Decimal("6")


def test_day_view_and_pdfs(login, supplier_a, placed_order):
    client = login(supplier_a.clerk)
    day = placed_order.delivery_date.isoformat()
    page = client.get(reverse("supplier_orders:day", args=[day])).content.decode()
    assert "Kommissionierliste" in page and placed_order.number in page
    for name in ("picking_pdf", "delivery_notes_pdf"):
        response = client.get(reverse(f"supplier_orders:{name}", args=[day]))
        assert response["Content-Type"] == "application/pdf" and response.content.startswith(b"%PDF")


def test_daily_digest(login, supplier_a, placed_order):
    from django.core.management import call_command

    profile = supplier_a.supplier_profile
    profile.notify_mode = "daily"
    profile.notify_digest_time = time(0, 0)
    profile.save()
    mail.outbox.clear()
    call_command("send_order_digests")
    assert len(mail.outbox) == 1 and mail.outbox[0].attachments[0][0] == "Kommissionierliste.pdf"
    call_command("send_order_digests")  # once per day only
    assert len(mail.outbox) == 1


def test_webhook_is_signed(supplier_a, placed_order, monkeypatch):
    import hashlib
    import hmac
    import json

    from apps.orders import notifications

    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout):
        sent["body"], sent["sig"] = req.data, req.headers["X-felicia-signature"]
        return Resp()

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)
    profile = supplier_a.supplier_profile
    profile.webhook_url = "https://erp.example.ch/hook"
    profile.save()
    notifications.send_webhook(placed_order)
    expected = hmac.new(notifications.webhook_secret(supplier_a).encode(), sent["body"], hashlib.sha256).hexdigest()
    assert sent["sig"] == f"sha256={expected}"
    assert json.loads(sent["body"])["number"] == placed_order.number
