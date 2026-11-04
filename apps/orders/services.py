"""Cart and checkout. One cart per user and customer organization; checkout splits it per supplier."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.services import log
from apps.catalog import pricing
from apps.catalog.models import Product, Variant
from apps.delivery import services as delivery

from .models import CartItem, Order, OrderLine

CENT = Decimal("0.01")


def visible_variants(tenant):
    return Variant.objects.filter(is_active=True, product__in=Product.objects.visible(tenant))


def check_quantity(variant, quantity):
    if quantity < variant.min_qty:
        raise ValidationError(f"Mindestmenge: {variant.min_qty.normalize()} {variant.unit}")
    if (quantity / variant.qty_step) % 1 != 0:
        raise ValidationError(f"Nur in Schritten von {variant.qty_step.normalize()} {variant.unit}")
    if variant.stock is not None and quantity > variant.stock:
        raise ValidationError(f"Nur noch {variant.stock.normalize()} {variant.unit} verfügbar")


def cart_items(customer, user):
    return (
        CartItem.objects.filter(customer=customer, user=user)
        .select_related("variant__product__supplier", "variant__product__category")
        .order_by("variant__product__supplier__name", "variant__product__name")
    )


def add_to_cart(*, customer, user, variant, quantity):
    item = CartItem.objects.filter(customer=customer, user=user, variant=variant).first()
    new_quantity = quantity + (item.quantity if item else 0)
    check_quantity(variant, new_quantity)
    if item:
        item.quantity = new_quantity
        item.save(update_fields=["quantity", "updated_at"])
    else:
        item = CartItem.objects.create(customer=customer, user=user, variant=variant, quantity=new_quantity)
    return item


def set_quantity(item, quantity):
    if quantity <= 0:
        item.delete()
        return None
    check_quantity(item.variant, quantity)
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


def cart_count(customer, user):
    return CartItem.objects.filter(customer=customer, user=user).count()


@dataclass
class SupplierGroup:
    supplier: object
    items: list = field(default_factory=list)
    quotes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def goods_value(self):
        return sum((i.line_total for i in self.items), Decimal("0"))

    @property
    def lead_days(self):
        return max((i.variant.product.lead_time_days for i in self.items), default=0)

    def quote_for(self, option_id):
        return next((q for q in self.quotes if q.option.pk == option_id), None)


def group_cart(customer, user, address=None, now=None):
    """Cart lines per supplier, with the delivery options that work for the chosen address."""
    by_supplier = defaultdict(list)
    for item in cart_items(customer, user):
        by_supplier[item.variant.product.supplier].append(item)
    groups = []
    for supplier, items in by_supplier.items():
        group = SupplierGroup(supplier=supplier, items=items)
        for item in items:
            product = item.variant.product
            if not (item.variant.is_active and product.is_active and supplier.status == "active"):
                group.errors.append(f"«{product.name}» ist nicht mehr erhältlich – bitte entfernen.")
            else:
                try:
                    check_quantity(item.variant, item.quantity)
                except ValidationError as exc:
                    group.errors.append(f"«{product.name}»: {exc.messages[0]}")
        zip_code = address.zip_code if address else ""
        canton = address.canton if address else ""
        group.quotes = delivery.quotes_for(supplier, zip_code, canton, group.goods_value, group.lead_days, now=now)
        if not address:
            group.quotes = [q for q in group.quotes if q.option.is_pickup]
        if not group.quotes:
            group.errors.append("Liefert nicht an diese Adresse und bietet keine Abholung an.")
        groups.append(group)
    return groups


def create_order(
    *, customer, supplier, user, quote, date, address, items, note, checkout_id, request=None, source="shop"
):
    """Write one order with its lines and book stock. items: [(locked Variant, quantity)]."""
    lines = [(v, q, (v.customer_price * q).quantize(CENT)) for v, q in items]
    goods = sum((t for _, _, t in lines), Decimal("0"))
    ship = address if address and not quote.option.is_pickup else None
    order = Order.objects.create(
        tenant=customer.tenant,
        number=Order.next_number(customer.tenant),
        checkout_id=checkout_id,
        customer=customer,
        supplier=supplier,
        placed_by=user,
        delivery_kind=quote.option.kind,
        delivery_name=quote.option.name,
        delivery_date=date,
        ship_name=ship.recipient if ship else "",
        ship_street=ship.street if ship else "",
        ship_zip=ship.zip_code if ship else "",
        ship_city=ship.city if ship else "",
        ship_notes=ship.delivery_notes if ship else "",
        customer_note=note,
        goods_total=goods,
        delivery_fee=quote.fee,
        total=goods + quote.fee,
        commission_percent=pricing.commission_for(supplier),
    )
    OrderLine.objects.bulk_create(
        [
            OrderLine(
                order=order,
                variant=v,
                product_name=v.product.name,
                variant_name=v.name,
                unit=v.unit,
                sku=v.sku,
                temperature=v.product.temperature,
                quantity=q,
                unit_price=v.customer_price,
                vat_rate=v.vat_rate,
                line_total=t,
            )
            for v, q, t in lines
        ]
    )
    for v, q, _ in lines:
        if v.stock is not None:
            v.stock -= q
            v.save(update_fields=["stock"])
    log(
        "order.placed",
        request=request,
        actor=user,
        organization=customer,
        target=order,
        changes={"lieferant": supplier.name, "total": str(order.total), "quelle": source},
    )
    return order


@transaction.atomic
def place_orders(*, request, customer, user, address, choices, note=""):
    """choices: {supplier_id: (option_id, date)}. Creates one order per supplier or raises ValidationError."""
    groups = group_cart(customer, user, address)
    if not groups:
        raise ValidationError("Der Warenkorb ist leer.")
    # lock variants to keep stock consistent
    variant_ids = [i.variant_id for g in groups for i in g.items]
    locked = {v.pk: v for v in Variant.objects.select_for_update().filter(pk__in=variant_ids)}
    checkout_id = uuid.uuid4()
    orders = []
    for group in groups:
        if group.errors:
            raise ValidationError(f"{group.supplier.name}: {group.errors[0]}")
        option_id, date = choices.get(group.supplier.pk, (None, None))
        quote = group.quote_for(option_id)
        if quote is None:
            raise ValidationError(f"{group.supplier.name}: Bitte Lieferart wählen.")
        if quote.missing_to_minimum > 0:
            raise ValidationError(
                f"{group.supplier.name}: Mindestbestellwert CHF {quote.min_order_value} "
                f"(es fehlen CHF {quote.missing_to_minimum})."
            )
        if date not in quote.dates:
            raise ValidationError(f"{group.supplier.name}: Bitte einen gültigen Liefertermin wählen.")
        for item in group.items:
            check_quantity(locked[item.variant_id], item.quantity)
        order = create_order(
            customer=customer,
            supplier=group.supplier,
            user=user,
            quote=quote,
            date=date,
            address=address,
            items=[(locked[i.variant_id], i.quantity) for i in group.items],
            note=note,
            checkout_id=checkout_id,
            request=request,
        )
        orders.append(order)
    CartItem.objects.filter(customer=customer, user=user).delete()
    from .notifications import notify_new_orders

    transaction.on_commit(lambda: notify_new_orders([o.pk for o in orders]))
    return orders


@transaction.atomic
def change_status(*, order, status, request):
    order = Order.objects.select_for_update().get(pk=order.pk)
    allowed = {
        "new": {"confirmed", "cancelled"},
        "confirmed": {"packed", "delivered", "cancelled"},
        "packed": {"delivered", "cancelled"},
    }
    if status not in allowed.get(order.status, set()):
        raise ValidationError("Dieser Statuswechsel ist nicht möglich.")
    old = order.status
    order.status = status
    order.status_changed_at = timezone.now()
    order.save(update_fields=["status", "status_changed_at", "updated_at"])
    if status == Order.Status.CANCELLED:
        for line in order.lines.all():
            if line.variant_id:
                Variant.objects.filter(pk=line.variant_id, stock__isnull=False).update(stock=F("stock") + line.quantity)
    log("order.status", request=request, organization=order.supplier, target=order, changes={"status": [old, status]})
    if status == Order.Status.DELIVERED:
        from apps.billing.services import invoice_on_delivery

        invoice_on_delivery(order)
    from .notifications import notify_status_change

    transaction.on_commit(lambda: notify_status_change(order.pk, old))
    return order


def reorder(*, order, customer, user):
    """Put the lines of an earlier order back into the cart; returns names that are no longer available."""
    missing = []
    visible = visible_variants(customer.tenant)
    for line in order.lines.all():
        variant = visible.filter(pk=line.variant_id).first() if line.variant_id else None
        if variant is None:
            missing.append(f"{line.product_name} {line.variant_name}")
            continue
        try:
            add_to_cart(customer=customer, user=user, variant=variant, quantity=line.quantity)
        except ValidationError:
            missing.append(f"{line.product_name} {line.variant_name}")
    return missing


def round_money(value):
    return Decimal(value).quantize(CENT)
