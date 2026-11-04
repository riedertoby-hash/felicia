"""Figures for suppliers and the operator. Revenue = goods value of non-cancelled orders by delivery date."""

from collections import OrderedDict
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncMonth

from apps.billing.models import Invoice
from apps.orders.models import Order, OrderLine

ZERO = Decimal("0")


def orders_in(period, **filters):
    return Order.objects.filter(delivery_date__range=(period.start, period.end), **filters).exclude(
        status=Order.Status.CANCELLED
    )


def kpis(orders):
    agg = orders.aggregate(n=Count("pk"), goods=Sum("goods_total"), fees=Sum("delivery_fee"))
    goods = agg["goods"] or ZERO
    commission = ExpressionWrapper(
        F("goods_total") * F("commission_percent") / 100, output_field=DecimalField(max_digits=12, decimal_places=4)
    )
    commission_total = orders.aggregate(c=Sum(commission))["c"] or ZERO
    customers = orders.values("customer").distinct().count()
    return {
        "orders": agg["n"],
        "goods": goods,
        "fees": agg["fees"] or ZERO,
        "average": (goods / agg["n"]).quantize(Decimal("0.01")) if agg["n"] else ZERO,
        "commission": commission_total.quantize(Decimal("0.01")),
        "customers": customers,
    }


def monthly(orders, start, end):
    """Revenue per month over the period, every month present (also empty ones), for the bar chart."""
    data = {
        row["m"].date() if hasattr(row["m"], "date") else row["m"]: row["goods"] or ZERO
        for row in orders.annotate(m=TruncMonth("delivery_date")).values("m").annotate(goods=Sum("goods_total"))
    }
    result, cursor = OrderedDict(), date(start.year, start.month, 1)
    while cursor <= end:
        result[cursor] = data.get(cursor, ZERO)
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    peak = max(result.values(), default=ZERO) or Decimal("1")
    return [{"month": m, "value": v, "pct": int(v / peak * 100)} for m, v in result.items()]


def top_products(orders, limit=10):
    return (
        OrderLine.objects.filter(order__in=orders)
        .values("product_name", "variant_name", "unit")
        .annotate(qty=Sum("quantity"), revenue=Sum("line_total"), n=Count("order", distinct=True))
        .order_by("-revenue")[:limit]
    )


def top_customers(orders, limit=10):
    return (
        orders.values("customer__name").annotate(revenue=Sum("goods_total"), n=Count("pk")).order_by("-revenue")[:limit]
    )


def by_supplier(orders):
    commission = ExpressionWrapper(
        F("goods_total") * F("commission_percent") / 100, output_field=DecimalField(max_digits=12, decimal_places=4)
    )
    return (
        orders.values("supplier__pk", "supplier__name")
        .annotate(revenue=Sum("goods_total"), n=Count("pk"), commission=Sum(commission))
        .order_by("-revenue")
    )


def open_invoices(**filters):
    return Invoice.objects.filter(status="open", **filters).aggregate(s=Sum("total"), n=Count("pk"))
