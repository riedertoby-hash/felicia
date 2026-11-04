from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Sequence, TenantModel, TimeStampedModel

MONEY = {"max_digits": 10, "decimal_places": 2}


class CartItem(TimeStampedModel):
    """One line in a user's cart for one customer organization."""

    customer = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="cart_items")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items")
    variant = models.ForeignKey("catalog.Variant", on_delete=models.CASCADE, related_name="+")
    quantity = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["customer", "user", "variant"], name="cart_unique_variant")]

    @property
    def line_total(self):
        return (self.variant.customer_price * self.quantity).quantize(Decimal("0.01"))


class Order(TenantModel):
    """An order of one customer at one supplier. A checkout creates one order per supplier."""

    class Status(models.TextChoices):
        NEW = "new", "Neu"
        CONFIRMED = "confirmed", "Bestätigt"
        PACKED = "packed", "Bereit"
        DELIVERED = "delivered", "Geliefert"
        CANCELLED = "cancelled", "Storniert"

    number = models.CharField("Bestellnummer", max_length=20, unique=True)
    checkout_id = models.UUIDField(db_index=True)
    customer = models.ForeignKey("orgs.Organization", on_delete=models.PROTECT, related_name="orders_placed")
    supplier = models.ForeignKey("orgs.Organization", on_delete=models.PROTECT, related_name="orders_received")
    placed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    # delivery (snapshot)
    delivery_kind = models.CharField(max_length=16)
    delivery_name = models.CharField(max_length=80)
    delivery_date = models.DateField(db_index=True)
    ship_name = models.CharField(max_length=200, blank=True)
    ship_street = models.CharField(max_length=200, blank=True)
    ship_zip = models.CharField(max_length=4, blank=True)
    ship_city = models.CharField(max_length=100, blank=True)
    ship_notes = models.CharField(max_length=300, blank=True)
    customer_note = models.TextField("Bemerkung", blank=True)
    supplier_note = models.TextField("Interne Notiz", blank=True)
    # money (snapshot)
    goods_total = models.DecimalField(**MONEY)
    delivery_fee = models.DecimalField(**MONEY, default=Decimal("0"))
    total = models.DecimalField(**MONEY)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    status_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["supplier", "delivery_date"]), models.Index(fields=["customer", "-created_at"])]

    def __str__(self):
        return self.number

    @classmethod
    def next_number(cls, tenant):
        year = timezone.localdate().year
        return f"B{year}-{Sequence.next(f'order:{tenant.pk}:{year}'):05d}"

    @property
    def commission_amount(self):
        return (self.goods_total * self.commission_percent / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def is_open(self):
        return self.status in (self.Status.NEW, self.Status.CONFIRMED, self.Status.PACKED)

    @property
    def is_pickup(self):
        return self.delivery_kind == "pickup"

    NEXT_STATUS = {
        "new": ("confirmed", "Bestätigen"),
        "confirmed": ("packed", "Als bereit markieren"),
        "packed": ("delivered", "Als geliefert markieren"),
    }

    @property
    def next_step(self):
        return self.NEXT_STATUS.get(self.status)


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey("catalog.Variant", null=True, on_delete=models.SET_NULL, related_name="+")
    product_name = models.CharField(max_length=120)
    variant_name = models.CharField(max_length=60)
    unit = models.CharField(max_length=10)
    sku = models.CharField(max_length=40, blank=True)
    temperature = models.CharField(max_length=16)
    quantity = models.DecimalField(max_digits=8, decimal_places=2)
    unit_price = models.DecimalField(**MONEY)
    vat_rate = models.CharField(max_length=4)
    line_total = models.DecimalField(**MONEY)

    class Meta:
        ordering = ["product_name", "variant_name"]

    def __str__(self):
        return f"{self.quantity} × {self.product_name} {self.variant_name}"


class StandingOrder(TimeStampedModel):
    """Recurring order: the same items every week or every two weeks on a fixed delivery weekday."""

    class Interval(models.IntegerChoices):
        WEEKLY = 1, "Jede Woche"
        BIWEEKLY = 2, "Alle 2 Wochen"
        FOURWEEKLY = 4, "Alle 4 Wochen"

    customer = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="standing_orders")
    supplier = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="standing_orders_received")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField("Bezeichnung", max_length=80, blank=True, help_text="z.B. Gemüse Wochenstart")
    option = models.ForeignKey(
        "delivery.DeliveryOption", on_delete=models.PROTECT, related_name="+", verbose_name="Lieferart"
    )
    address = models.ForeignKey(
        "customers.Address",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="Lieferadresse",
    )
    interval_weeks = models.PositiveSmallIntegerField("Rhythmus", choices=Interval.choices, default=1)
    first_date = models.DateField("Erste Lieferung")
    end_date = models.DateField("Endet am", null=True, blank=True, help_text="Leer = unbefristet")
    paused_until = models.DateField("Pausiert bis", null=True, blank=True)
    skipped_dates = models.JSONField(default=list, blank=True)
    note = models.CharField("Bemerkung für den Lieferanten", max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    last_generated_date = models.DateField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["supplier__name", "first_date"]

    def __str__(self):
        return self.name or f"Dauerauftrag bei {self.supplier}"

    def occurs_on(self, day):
        if day < self.first_date or (self.end_date and day > self.end_date):
            return False
        return (day - self.first_date).days % (7 * self.interval_weeks) == 0

    def upcoming(self, from_day, count=4):
        """Next delivery dates from `from_day` on, with a flag whether they are skipped/paused."""
        from datetime import timedelta

        step = timedelta(weeks=self.interval_weeks)
        day = self.first_date
        if from_day > day:
            periods = -(-(from_day - day).days // step.days)
            day = day + step * periods
        result = []
        while len(result) < count and (not self.end_date or day <= self.end_date):
            result.append({"date": day, "skipped": self.is_skipped(day)})
            day += step
        return result

    def is_skipped(self, day):
        return day.isoformat() in self.skipped_dates or bool(self.paused_until and day <= self.paused_until)

    @property
    def weekday_label(self):
        return ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][
            self.first_date.weekday()
        ]


class StandingOrderItem(models.Model):
    standing_order = models.ForeignKey(StandingOrder, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.Variant", on_delete=models.CASCADE, related_name="+")
    quantity = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["standing_order", "variant"], name="standing_item_unique")]

    def __str__(self):
        return f"{self.quantity} × {self.variant}"
