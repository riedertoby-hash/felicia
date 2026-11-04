"""Delivery rules: which options reach an address, possible dates, minimum order and fees."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import DeliveryOption

DATES_SHOWN = 6


@dataclass
class Quote:
    option: DeliveryOption
    zone: object  # DeliveryZone or None for pickup
    fee: Decimal
    min_order_value: Decimal
    dates: list
    goods_value: Decimal = Decimal("0")

    @property
    def missing_to_minimum(self):
        return max(Decimal("0"), self.min_order_value - self.goods_value)

    @property
    def ok(self):
        return self.missing_to_minimum == 0 and bool(self.dates)


def zone_for(option, zip_code, canton=""):
    if option.is_pickup:
        return None
    for zone in option.zones.all():
        if zone.covers(zip_code, canton):
            return zone
    return False


def possible_dates(option, product_lead_days=0, now=None, count=DATES_SHOWN):
    """Next dates on the option's weekdays that respect the option's and the products' lead time."""
    if not option.weekdays:
        return []
    now = timezone.localtime(now or timezone.now())
    lead = max(option.lead_days, product_lead_days)
    first = now.date() + timedelta(days=lead)
    if now.time() > option.cutoff_time:
        first += timedelta(days=1)
    dates, day = [], first
    while len(dates) < count and day < first + timedelta(days=60):
        if day.weekday() in option.weekdays:
            dates.append(day)
        day += timedelta(days=1)
    return dates


def is_date_allowed(option, date, product_lead_days=0, now=None):
    return date in possible_dates(option, product_lead_days, now=now, count=60)


def quotes_for(supplier, zip_code, canton, goods_value, product_lead_days=0, now=None):
    """All delivery options of a supplier usable for this address, with fee and dates."""
    result = []
    for option in supplier.delivery_options.filter(is_active=True).prefetch_related("zones__fee_tiers"):
        zone = zone_for(option, zip_code, canton)
        if zone is False:
            continue
        fee = zone.fee_for(goods_value) if zone else Decimal("0")
        minimum = zone.min_order_value if zone else Decimal("0")
        result.append(
            Quote(
                option=option,
                zone=zone,
                fee=fee,
                min_order_value=minimum,
                dates=possible_dates(option, product_lead_days, now=now),
                goods_value=goods_value,
            )
        )
    return result


def delivers_to(supplier_ids, zip_code, canton=""):
    """Subset of supplier ids that can serve the address (any pickup counts too)."""
    from .models import DeliveryZone

    reachable = set(
        DeliveryOption.objects.filter(supplier_id__in=supplier_ids, is_active=True, kind="pickup").values_list(
            "supplier_id", flat=True
        )
    )
    for zone in DeliveryZone.objects.filter(
        option__supplier_id__in=supplier_ids, option__is_active=True
    ).select_related("option"):
        if zone.covers(zip_code, canton):
            reachable.add(zone.option.supplier_id)
    return reachable
