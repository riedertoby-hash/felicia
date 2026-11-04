from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.orders import standing
from apps.orders.models import Order, StandingOrder
from tests.test_orders import add, address, checkout, setup_supplier, tomorrow  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def first_order(login, customer, supplier_a, address):  # noqa: F811
    option, _, variant = setup_supplier(supplier_a)
    option.weekdays = [1]  # Tuesdays
    option.lead_days = 1
    option.cutoff_time = time(18, 0)
    option.save()
    client = login(customer.owner)
    add(client, variant, 6)
    day = next(d for d in (tomorrow() + timedelta(days=i) for i in range(8)) if d.weekday() == 1)
    checkout(client, address, {supplier_a.pk: (option.pk, day)})
    return Order.objects.get()


def next_tuesday(after):
    return next(after + timedelta(days=i) for i in range(1, 8) if (after + timedelta(days=i)).weekday() == 1)


def at(day, hour):
    return timezone.make_aware(datetime.combine(day, time(hour, 0)))


@pytest.fixture
def standing_order(customer, first_order):
    first = next_tuesday(timezone.localdate() + timedelta(days=7))
    return standing.create_from_order(order=first_order, user=customer.owner, interval_weeks=1, first_date=first)


def test_create_from_order_via_page(login, customer, first_order):
    client = login(customer.owner)
    page = client.get(reverse("orders:standing_create", args=[first_order.pk])).content.decode()
    first = next_tuesday(timezone.localdate() + timedelta(days=7)).isoformat()
    assert first in page
    client.post(
        reverse("orders:standing_create", args=[first_order.pk]),
        {"name": "Wochengemüse", "interval_weeks": "1", "first_date": first},
    )
    s = StandingOrder.objects.get()
    assert s.name == "Wochengemüse" and s.items.get().quantity == Decimal("6") and s.address is not None


def test_order_is_created_only_shortly_before_the_deadline(standing_order, django_capture_on_commit_callbacks):
    day = standing_order.first_date  # a Tuesday
    deadline_day = day - timedelta(days=1)  # Monday 18:00 is the order deadline (lead 1 day)
    assert standing.run(now=at(deadline_day - timedelta(days=3), 10)) == ([], [])  # too early
    assert standing.run(now=at(deadline_day, 5)) == ([], [])  # still more than 12 h before the deadline
    with django_capture_on_commit_callbacks(execute=True):
        created, problems = standing.run(now=at(deadline_day, 9))
    assert len(created) == 1 and not problems
    order = created[0]
    assert order.delivery_date == day and order.goods_total == Decimal("60.00")
    assert any("Neue Bestellung" in m.subject for m in mail.outbox)
    assert standing.run(now=at(deadline_day, 12)) == ([], [])  # never twice for the same date


def test_skipped_and_paused_dates_are_not_ordered(standing_order):
    day = standing_order.first_date
    standing_order.skipped_dates = [day.isoformat()]
    standing_order.save()
    assert standing.run(now=at(day - timedelta(days=1), 9)) == ([], [])
    standing_order.skipped_dates = []
    standing_order.paused_until = day + timedelta(days=7)
    standing_order.save()
    assert standing.run(now=at(day - timedelta(days=1), 9)) == ([], [])
    following = day + timedelta(days=14)
    created, _ = standing.run(now=at(following - timedelta(days=1), 9))
    assert created[0].delivery_date == following


def test_unavailable_items_are_reported(standing_order, django_capture_on_commit_callbacks):
    variant = standing_order.items.get().variant
    variant.product.is_active = False
    variant.product.save()
    mail.outbox.clear()
    day = standing_order.first_date
    created, problems = standing.run(now=at(day - timedelta(days=1), 9))
    assert not created and len(problems) == 1
    assert "Keiner der Artikel ist erhältlich" in problems[0][1]
    assert mail.outbox[0].to == ["chef@restaurant.ch"]
    standing_order.refresh_from_db()
    assert standing_order.last_error


def test_quantity_edit_skip_and_end(login, customer, standing_order):
    client = login(customer.owner)
    url = reverse("orders:standing", args=[standing_order.pk])
    item = standing_order.items.get()
    client.post(url, {"action": "quantities", f"qty_{item.pk}": "1"})  # below minimum 2
    item.refresh_from_db()
    assert item.quantity == Decimal("6")
    client.post(url, {"action": "quantities", f"qty_{item.pk}": "8"})
    item.refresh_from_db()
    assert item.quantity == Decimal("8")
    client.post(url, {"action": "skip", "date": standing_order.first_date.isoformat()})
    standing_order.refresh_from_db()
    assert standing_order.is_skipped(standing_order.first_date)
    client.post(url, {"action": "end"})
    standing_order.refresh_from_db()
    assert not standing_order.is_active


def test_isolation(login, tenant, supplier_a, supplier_b, standing_order):
    from apps.orgs.services import create_organization
    from tests.conftest import make_user

    other = create_organization(tenant=tenant, kind="customer", name="Bären", owner=make_user("chef@baeren.ch"))
    client = login(other.memberships.get().user)
    assert client.get(reverse("orders:standing", args=[standing_order.pk])).status_code == 404
    assert client.post(reverse("orders:standing", args=[standing_order.pk]), {"action": "end"}).status_code == 404
    assert "Restaurant Linde" in login(supplier_a.clerk).get(reverse("supplier_orders:standing")).content.decode()
    assert "Restaurant Linde" not in login(supplier_b.owner).get(reverse("supplier_orders:standing")).content.decode()


def test_upcoming_dates_biweekly(standing_order):
    standing_order.interval_weeks = 2
    first = standing_order.first_date
    dates = [d["date"] for d in standing_order.upcoming(first + timedelta(days=1), count=2)]
    assert dates == [first + timedelta(days=14), first + timedelta(days=28)]
