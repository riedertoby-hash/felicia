"""Picking list and day overview data (shared by HTML print views, PDFs and the daily digest)."""

from collections import OrderedDict
from decimal import Decimal

from .models import Order, OrderLine

TEMPERATURE_ORDER = {"frozen": 0, "chilled": 1, "ambient": 2}
TEMPERATURE_LABEL = {"frozen": "Tiefgekühlt", "chilled": "Gekühlt", "ambient": "Ungekühlt"}


def orders_for_day(supplier, day):
    return (
        Order.objects.filter(supplier=supplier, delivery_date=day)
        .exclude(status=Order.Status.CANCELLED)
        .select_related("customer")
        .prefetch_related("lines")
        .order_by("delivery_kind", "ship_zip", "number")
    )


def picking_list(orders):
    """Total quantity per variant, grouped by temperature (frozen first, so it is packed last)."""
    totals = OrderedDict()
    lines = OrderLine.objects.filter(order__in=orders).order_by("temperature", "product_name", "variant_name")
    for line in lines:
        key = (line.temperature, line.product_name, line.variant_name, line.unit, line.sku)
        entry = totals.setdefault(key, {"quantity": Decimal("0"), "orders": 0})
        entry["quantity"] += line.quantity
        entry["orders"] += 1
    groups = OrderedDict()
    for (temp, product, variant, unit, sku), data in sorted(
        totals.items(), key=lambda kv: (TEMPERATURE_ORDER.get(kv[0][0], 9), kv[0][1])
    ):
        groups.setdefault(TEMPERATURE_LABEL.get(temp, temp), []).append(
            {"product": product, "variant": variant, "unit": unit, "sku": sku, **data}
        )
    return groups
