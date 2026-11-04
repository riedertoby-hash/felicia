"""Standing orders: create, and the daily job that turns them into normal orders at the order deadline."""

import logging
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log
from apps.catalog.models import Variant
from apps.delivery import services as delivery

from .models import StandingOrder, StandingOrderItem
from .services import check_quantity, create_order, visible_variants

logger = logging.getLogger(__name__)
DEADLINE_WINDOW = timedelta(hours=12)  # orders are created in the last 12 hours before the order deadline


@transaction.atomic
def create_from_order(*, order, user, interval_weeks, first_date, name="", request=None):
    """Turn an earlier order into a standing order with the same supplier, delivery and items."""
    option = order.supplier.delivery_options.filter(
        is_active=True, name=order.delivery_name, kind=order.delivery_kind
    ).first()
    if option is None:
        raise ValidationError("Die Lieferart dieser Bestellung gibt es nicht mehr – bitte im Shop neu bestellen.")
    if first_date.weekday() not in option.weekdays:
        raise ValidationError(f"{option.name} gibt es nur am {option.weekday_labels}.")
    address = None
    if not option.is_pickup:
        address = (
            order.customer.addresses.filter(zip_code=order.ship_zip, street=order.ship_street).first()
            or order.customer.addresses.filter(is_default=True).first()
        )
        if address is None:
            raise ValidationError("Bitte zuerst eine Lieferadresse erfassen.")
    standing = StandingOrder.objects.create(
        customer=order.customer,
        supplier=order.supplier,
        created_by=user,
        name=name[:80],
        option=option,
        address=address,
        interval_weeks=interval_weeks,
        first_date=first_date,
        note=order.customer_note[:300],
    )
    visible = visible_variants(order.tenant)
    for line in order.lines.all():
        if line.variant_id and visible.filter(pk=line.variant_id).exists():
            StandingOrderItem.objects.create(
                standing_order=standing, variant_id=line.variant_id, quantity=line.quantity
            )
    if not standing.items.exists():
        raise ValidationError("Keiner der Artikel ist noch erhältlich.")
    log(
        "standing.created",
        request=request,
        organization=order.customer,
        target=standing,
        changes={"lieferant": order.supplier.name, "ab": str(first_date), "rhythmus": interval_weeks},
    )
    return standing


def due_occurrence(standing, now):
    """The delivery date to order for right now, or None.

    An occurrence is ordered as late as possible: when it is the earliest date the delivery option still
    accepts (order deadline reached). Until then the customer can change or skip it."""
    if not standing.is_active:
        return None
    lead = max((i.variant.product.lead_time_days for i in standing.items.all()), default=0)
    possible = delivery.possible_dates(standing.option, lead, now=now, count=1)
    if not possible:
        return None
    day = possible[0]
    if not standing.occurs_on(day) or standing.is_skipped(day):
        return None
    # Wait until the order deadline for this date is close: if the date is still orderable after the
    # window, the customer keeps time to change or skip it.
    later = delivery.possible_dates(standing.option, lead, now=now + DEADLINE_WINDOW, count=1)
    if later and later[0] <= day:
        return None
    if standing.last_generated_date and day <= standing.last_generated_date:
        return None
    return day


def run(now=None):
    """Daily/periodic job. Returns (orders created, problems)."""
    now = now or timezone.now()
    created, problems = [], []
    qs = (
        StandingOrder.objects.filter(is_active=True)
        .select_related("customer__tenant", "supplier", "option", "address", "created_by")
        .prefetch_related("items__variant__product")
    )
    for standing in qs:
        day = due_occurrence(standing, now)
        if day is None:
            continue
        try:
            created.append(generate(standing, day, now))
        except ValidationError as exc:
            message = exc.messages[0]
            StandingOrder.objects.filter(pk=standing.pk).update(last_generated_date=day, last_error=message[:300])
            problems.append((standing, message))
            _notify_problem(standing, day, message)
    return created, problems


@transaction.atomic
def generate(standing, day, now):
    if standing.supplier.status != "active" or standing.customer.status != "active":
        raise ValidationError("Lieferant oder Kunde ist zurzeit gesperrt.")
    visible = set(visible_variants(standing.customer.tenant).values_list("pk", flat=True))
    locked = {
        v.pk: v
        for v in Variant.objects.select_for_update()
        .select_related("product")
        .filter(pk__in=[i.variant_id for i in standing.items.all()])
    }
    items, missing = [], []
    for item in standing.items.all():
        variant = locked.get(item.variant_id)
        if variant is None or variant.pk not in visible:
            missing.append(item.variant.product.name)
            continue
        try:
            check_quantity(variant, item.quantity)
        except ValidationError as exc:
            missing.append(f"{variant.product.name} ({exc.messages[0]})")
            continue
        items.append((variant, item.quantity))
    if not items:
        raise ValidationError("Keiner der Artikel ist erhältlich: " + ", ".join(missing))
    goods = sum((v.customer_price * q for v, q in items), 0)
    quotes = delivery.quotes_for(
        standing.supplier,
        standing.address.zip_code if standing.address else "",
        standing.address.canton if standing.address else "",
        goods,
        max(v.product.lead_time_days for v, _ in items),
        now=now,
    )
    quote = next((q for q in quotes if q.option.pk == standing.option_id), None)
    if quote is None:
        raise ValidationError("Die Lieferart passt nicht mehr zur Lieferadresse.")
    if quote.missing_to_minimum > 0:
        raise ValidationError(
            f"Mindestbestellwert CHF {quote.min_order_value} nicht erreicht (es fehlen CHF {quote.missing_to_minimum})."
        )
    note = standing.note
    if missing:
        note = (note + " · " if note else "") + "Nicht erhältlich: " + ", ".join(missing)
    order = create_order(
        customer=standing.customer,
        supplier=standing.supplier,
        user=standing.created_by,
        quote=quote,
        date=day,
        address=standing.address,
        items=items,
        note=note[:1000],
        checkout_id=uuid.uuid4(),
        source="dauerauftrag",
    )
    standing.last_generated_date, standing.last_error = day, ""
    standing.save(update_fields=["last_generated_date", "last_error", "updated_at"])
    from .notifications import notify_new_orders

    transaction.on_commit(lambda: notify_new_orders([order.pk]))
    return order


def _notify_problem(standing, day, message):
    to = standing.created_by.email if standing.created_by else ""
    if not to:
        return
    try:
        send_mail(
            subject=f"Dauerauftrag bei {standing.supplier.name}: Lieferung vom {day:%d.%m.%Y} nicht bestellt",
            message=(
                f"Guten Tag\n\nIhr Dauerauftrag «{standing}» konnte für den {day:%d.%m.%Y} nicht "
                f"ausgelöst werden:\n{message}\n\nBitte prüfen Sie den Dauerauftrag im Portal oder bestellen "
                "Sie diesmal über den Shop.\n"
            ),
            from_email=None,
            recipient_list=[to],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Hinweis zu Dauerauftrag %s nicht versendet", standing.pk)
