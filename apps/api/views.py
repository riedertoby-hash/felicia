"""REST API v1 for suppliers' own systems (ERP, shop, warehouse). JSON only, token auth:
Authorization: Bearer fel_…
"""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from apps.audit.services import log
from apps.billing.models import Invoice
from apps.catalog import pricing
from apps.catalog.models import Variant
from apps.core.rls import set_request_context
from apps.orders import services as order_services
from apps.orders.models import Order

from .models import ApiKey

RATE_LIMIT = 120  # requests per minute and key
PAGE_SIZE = 100


def error(status, message):
    return JsonResponse({"error": message}, status=status)


def api(scope, methods=("GET",)):
    def decorator(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return error(405, "Methode nicht erlaubt")
            header = request.headers.get("Authorization", "")
            key = ApiKey.authenticate(header[7:].strip() if header.startswith("Bearer ") else "")
            if key is None:
                return error(401, "Ungültiger oder fehlender API-Schlüssel")
            if scope not in key.scopes:
                return error(403, f"Schlüssel hat keine Berechtigung «{scope}»")
            bucket = f"api-rate:{key.pk}:{timezone.now():%Y%m%d%H%M}"
            count = cache.get_or_set(bucket, 0, 70)
            if count >= RATE_LIMIT:
                return error(429, "Zu viele Anfragen – bitte kurz warten")
            cache.incr(bucket)
            request.api_key, request.org = key, key.organization
            # Database row-level security: act exactly as this organization.
            set_request_context(key.organization, key.organization.tenant)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError as exc:
        raise ValidationError("Ungültiges JSON") from exc


def _page(qs, request):
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    items = list(qs[(page - 1) * PAGE_SIZE : page * PAGE_SIZE + 1])
    return items[:PAGE_SIZE], (page + 1 if len(items) > PAGE_SIZE else None)


def order_json(o):
    return {
        "number": o.number,
        "status": o.status,
        "created_at": o.created_at.isoformat(),
        "delivery": {
            "kind": o.delivery_kind,
            "name": o.delivery_name,
            "date": o.delivery_date.isoformat(),
            "recipient": o.ship_name,
            "street": o.ship_street,
            "zip": o.ship_zip,
            "city": o.ship_city,
            "notes": o.ship_notes,
        },
        "customer": {"name": o.customer.name},
        "note": o.customer_note,
        "lines": [
            {
                "sku": line.sku,
                "product": line.product_name,
                "variant": line.variant_name,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "unit_price": str(line.unit_price),
                "vat_rate": line.vat_rate,
                "total": str(line.line_total),
            }
            for line in o.lines.all()
        ],
        "goods_total": str(o.goods_total),
        "delivery_fee": str(o.delivery_fee),
        "total": str(o.total),
        "invoice": o.invoice.number if o.invoice_id else None,
    }


@api("orders.read")
def orders(request):
    qs = (
        Order.objects.filter(supplier=request.org)
        .select_related("customer", "invoice")
        .prefetch_related("lines")
        .order_by("-created_at")
    )
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("since"):
        try:
            qs = qs.filter(updated_at__gte=datetime.fromisoformat(request.GET["since"]))
        except ValueError:
            return error(400, "since: ISO-Datum erwartet, z.B. 2026-11-01T00:00:00")
    if request.GET.get("delivery_date"):
        qs = qs.filter(delivery_date=request.GET["delivery_date"])
    items, next_page = _page(qs, request)
    return JsonResponse({"results": [order_json(o) for o in items], "next_page": next_page})


@api("orders.read")
def order_detail(request, number):
    order = Order.objects.filter(supplier=request.org, number=number).select_related("customer", "invoice").first()
    if order is None:
        return error(404, "Bestellung nicht gefunden")
    return JsonResponse(order_json(order))


@api("orders.write", methods=("POST",))
def order_status(request, number):
    order = Order.objects.filter(supplier=request.org, number=number).first()
    if order is None:
        return error(404, "Bestellung nicht gefunden")
    try:
        order_services.change_status(order=order, status=_body(request).get("status", ""), request=request)
    except ValidationError as exc:
        return error(400, exc.messages[0])
    order.refresh_from_db()
    return JsonResponse(order_json(order))


def variant_json(v, commission):
    return {
        "sku": v.sku,
        "product": v.product.name,
        "variant": v.name,
        "unit": v.unit,
        "customer_price": str(v.customer_price),
        "supplier_price": str(pricing.supplier_net(v.customer_price, commission)),
        "vat_rate": v.vat_rate,
        "min_qty": str(v.min_qty),
        "stock": str(v.stock) if v.stock is not None else None,
        "active": v.is_active and v.product.is_active,
    }


@api("catalog.read")
def products(request):
    commission = pricing.commission_for(request.org)
    qs = (
        Variant.objects.filter(product__supplier=request.org)
        .select_related("product")
        .order_by("product__name", "sort")
    )
    items, next_page = _page(qs, request)
    return JsonResponse(
        {
            "results": [variant_json(v, commission) for v in items],
            "next_page": next_page,
            "commission_percent": str(commission),
        }
    )


@api("stock.write", methods=("PATCH", "POST"))
def variant_update(request, sku):
    variant = Variant.objects.filter(product__supplier=request.org, sku=sku).select_related("product").first()
    if variant is None:
        return error(404, "Artikelnummer nicht gefunden")
    try:
        data = _body(request)
    except ValidationError as exc:
        return error(400, exc.messages[0])
    changes, fields = {}, []
    if "stock" in data:
        try:
            stock = None if data["stock"] is None else Decimal(str(data["stock"]))
        except InvalidOperation:
            return error(400, "stock: Zahl oder null erwartet")
        changes["stock"] = [str(variant.stock), str(stock)]
        variant.stock = stock
        fields.append("stock")
    if "customer_price" in data:
        if "prices.write" not in request.api_key.scopes:
            return error(403, "Schlüssel hat keine Berechtigung «prices.write»")
        try:
            price = pricing.round_5_rappen(Decimal(str(data["customer_price"])))
            if price <= 0:
                raise InvalidOperation
        except InvalidOperation:
            return error(400, "customer_price: positive Zahl erwartet")
        changes["customer_price"] = [str(variant.customer_price), str(price)]
        variant.customer_price = price
        fields.append("customer_price")
    if not fields:
        return error(400, "Nichts zu ändern: stock und/oder customer_price angeben")
    variant.save(update_fields=fields)
    log(
        "catalog.updated",
        request=request,
        actor=request.api_key.created_by,
        organization=request.org,
        target=variant.product,
        changes={**changes, "via": f"API {request.api_key.prefix}"},
    )
    return JsonResponse(variant_json(variant, pricing.commission_for(request.org)))


@api("invoices.read")
def invoices(request):
    qs = Invoice.objects.filter(issuer=request.org, kind="sale").select_related("recipient").order_by("-issue_date")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    items, next_page = _page(qs, request)
    return JsonResponse(
        {
            "results": [
                {
                    "number": i.number,
                    "customer": i.recipient.name,
                    "issue_date": i.issue_date.isoformat(),
                    "due_date": i.due_date.isoformat(),
                    "total": str(i.total),
                    "vat_total": str(i.vat_total),
                    "amount_due": str(i.amount_due),
                    "status": i.status,
                    "reference": i.reference,
                    "paid_at": i.paid_at.isoformat() if i.paid_at else None,
                }
                for i in items
            ],
            "next_page": next_page,
        }
    )
