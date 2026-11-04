import csv
import io
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.orgs.decorators import org_required

from . import documents, services
from .models import Order

KIND = "supplier"


def _orders(request):
    return Order.objects.filter(supplier=request.org)


def _parse_day(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@org_required("orders.view", kind=KIND)
def order_list(request):
    qs = _orders(request).select_related("customer")
    view = request.GET.get("ansicht", "offen")
    if view == "offen":
        qs = qs.filter(status__in=["new", "confirmed", "packed"]).order_by("delivery_date", "number")
    elif view == "neu":
        qs = qs.filter(status="new").order_by("created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
    today = timezone.localdate()
    upcoming = (
        _orders(request)
        .filter(delivery_date__gte=today)
        .exclude(status="cancelled")
        .values("delivery_date")
        .annotate(n=Count("pk"), total=Sum("total"))
        .order_by("delivery_date")[:7]
    )
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/supplier_list.html",
        {
            "page": page,
            "view": view,
            "q": q,
            "upcoming": upcoming,
            "new_count": _orders(request).filter(status="new").count(),
            "can_manage": request.membership.has_perm("orders.manage"),
        },
    )


@org_required("orders.view", kind=KIND)
def order_detail(request, pk):
    order = get_object_or_404(_orders(request).select_related("customer", "placed_by", "invoice"), pk=pk)
    can_manage = request.membership.has_perm("orders.manage")
    if request.method == "POST" and can_manage:
        order.supplier_note = request.POST.get("supplier_note", "")[:2000]
        order.save(update_fields=["supplier_note", "updated_at"])
        messages.success(request, "Notiz gespeichert.")
        return redirect("supplier_orders:detail", pk=pk)
    return render(
        request, "orders/supplier_detail.html", {"order": order, "lines": order.lines.all(), "can_manage": can_manage}
    )


@require_POST
@org_required("orders.manage", kind=KIND)
def set_status(request, pk):
    order = get_object_or_404(_orders(request), pk=pk)
    try:
        services.change_status(order=order, status=request.POST.get("status", ""), request=request)
        order.refresh_from_db()
        messages.success(request, f"{order.number}: {order.get_status_display()}")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    next_url = request.POST.get("next", "")
    if next_url.startswith("/lieferant/"):
        return redirect(next_url)
    return redirect("supplier_orders:detail", pk=pk)


@require_POST
@org_required("orders.manage", kind=KIND)
def confirm_all(request):
    count = 0
    for order in _orders(request).filter(status="new"):
        services.change_status(order=order, status="confirmed", request=request)
        count += 1
    messages.success(request, f"{count} Bestellung{'en' if count != 1 else ''} bestätigt.")
    return redirect("supplier_orders:list")


@org_required("orders.view", kind=KIND)
def day(request, day=None):
    the_day = _parse_day(day or request.GET.get("datum"), timezone.localdate())
    orders = documents.orders_for_day(request.org, the_day)
    return render(
        request,
        "orders/supplier_day.html",
        {
            "day": the_day,
            "orders": orders,
            "picking": documents.picking_list(orders),
            "prev": the_day - timedelta(days=1),
            "next": the_day + timedelta(days=1),
            "total": sum(o.total for o in orders),
        },
    )


def _pdf(template, context, filename):
    from apps.billing.pdf import render_pdf

    response = HttpResponse(render_pdf(template, context), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@org_required("orders.view", kind=KIND)
def picking_pdf(request, day):
    the_day = _parse_day(day, timezone.localdate())
    orders = documents.orders_for_day(request.org, the_day)
    return _pdf(
        "documents/picking_list.html",
        {"day": the_day, "supplier": request.org, "orders": orders, "picking": documents.picking_list(orders)},
        f"Kommissionierliste-{the_day}.pdf",
    )


@org_required("orders.view", kind=KIND)
def delivery_notes_pdf(request, day):
    the_day = _parse_day(day, timezone.localdate())
    orders = documents.orders_for_day(request.org, the_day)
    return _pdf("documents/delivery_note.html", {"orders": orders}, f"Lieferscheine-{the_day}.pdf")


@org_required("orders.view", kind=KIND)
def delivery_note_pdf(request, pk):
    order = get_object_or_404(_orders(request), pk=pk)
    return _pdf("documents/delivery_note.html", {"orders": [order]}, f"Lieferschein-{order.number}.pdf")


@org_required("orders.view", kind=KIND)
def export_csv(request):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Bestellung",
            "Datum",
            "Liefertermin",
            "Kunde",
            "Status",
            "Artikel",
            "Variante",
            "Menge",
            "Einheit",
            "Preis",
            "Total",
        ]
    )
    qs = _orders(request).select_related("customer").prefetch_related("lines").order_by("-created_at")[:5000]
    for o in qs:
        for line in o.lines.all():
            writer.writerow(
                [
                    o.number,
                    f"{o.created_at:%d.%m.%Y}",
                    f"{o.delivery_date:%d.%m.%Y}",
                    o.customer.name,
                    o.get_status_display(),
                    line.product_name,
                    line.variant_name,
                    line.quantity,
                    line.unit,
                    line.unit_price,
                    line.line_total,
                ]
            )
    response = HttpResponse(buf.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="bestellungen.csv"'
    return response
