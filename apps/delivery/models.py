import re
from datetime import time
from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel
from apps.suppliers.models import CANTONS

WEEKDAYS = [(0, "Mo"), (1, "Di"), (2, "Mi"), (3, "Do"), (4, "Fr"), (5, "Sa"), (6, "So")]
MONEY = {"max_digits": 9, "decimal_places": 2, "validators": [MinValueValidator(Decimal("0"))]}


def parse_zip_list(text):
    """'4410, 4411, 4400-4499' -> list of (from, to) ranges. Raises ValidationError on bad input."""
    ranges = []
    for part in re.split(r"[,;\s]+", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", part)
        if not m:
            raise ValidationError(f"«{part}» ist keine PLZ oder kein Bereich (z.B. 4410 oder 4400-4499).")
        low, high = int(m.group(1)), int(m.group(2) or m.group(1))
        if low > high:
            raise ValidationError(f"Bereich «{part}»: Start ist grösser als Ende.")
        ranges.append((low, high))
    return ranges


class DeliveryOption(TimeStampedModel):
    """How a supplier gets goods to customers: pickup, own delivery or a third-party carrier."""

    class Kind(models.TextChoices):
        PICKUP = "pickup", "Abholung"
        OWN = "own", "Lieferung durch uns"
        CARRIER = "carrier", "Lieferung durch Partner (Distribution)"

    supplier = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="delivery_options")
    kind = models.CharField("Art", max_length=16, choices=Kind.choices)
    name = models.CharField("Bezeichnung für Kunden", max_length=80, help_text="z.B. Hoflieferung Basel")
    weekdays = ArrayField(
        models.PositiveSmallIntegerField(choices=WEEKDAYS), default=list, verbose_name="Liefer-/Abholtage"
    )
    cutoff_time = models.TimeField(
        "Bestellschluss", default=time(18, 0), help_text="Bis zu dieser Uhrzeit zählt der Tag noch für die Vorlaufzeit"
    )
    lead_days = models.PositiveSmallIntegerField(
        "Vorlauf (Tage)", default=1, help_text="Mindestens so viele Tage zwischen Bestellung und Termin"
    )
    carrier_name = models.CharField("Partner", max_length=80, blank=True)
    notes = models.CharField("Hinweis für Kunden", max_length=200, blank=True)
    is_active = models.BooleanField("Aktiv", default=True)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "Lieferart"
        verbose_name_plural = "Lieferarten"

    def __str__(self):
        return self.name

    @property
    def is_pickup(self):
        return self.kind == self.Kind.PICKUP

    @property
    def weekday_labels(self):
        names = dict(WEEKDAYS)
        return ", ".join(names[d] for d in sorted(self.weekdays))


class DeliveryZone(models.Model):
    """Area served by a delivery option, with its own minimum order and fee tiers."""

    option = models.ForeignKey(DeliveryOption, on_delete=models.CASCADE, related_name="zones")
    name = models.CharField("Zone", max_length=60, help_text="z.B. Zone 1 – Liestal")
    zip_codes = models.TextField("Postleitzahlen", blank=True, help_text="z.B. 4410, 4411, 4400-4499")
    cantons = ArrayField(
        models.CharField(max_length=2, choices=CANTONS), default=list, blank=True, verbose_name="Ganze Kantone"
    )
    min_order_value = models.DecimalField("Mindestbestellwert (CHF)", default=Decimal("0"), **MONEY)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "pk"]
        verbose_name = "Lieferzone"
        verbose_name_plural = "Lieferzonen"

    def __str__(self):
        return self.name

    def clean(self):
        parse_zip_list(self.zip_codes)
        if not self.zip_codes.strip() and not self.cantons:
            raise ValidationError("Bitte Postleitzahlen oder Kantone angeben.")

    def covers(self, zip_code, canton=""):
        try:
            number = int(zip_code)
        except (TypeError, ValueError):
            return False
        if canton and canton in self.cantons:
            return True
        return any(low <= number <= high for low, high in parse_zip_list(self.zip_codes))

    def fee_for(self, order_value):
        """Fee of the highest tier whose threshold the order value reaches; no tiers = free."""
        fee = Decimal("0")
        for tier in self.fee_tiers.all():  # ordered ascending by threshold
            if order_value >= tier.from_value:
                fee = tier.fee
        return fee


class FeeTier(models.Model):
    """«Ab Warenwert X kostet die Lieferung Y» – e.g. 0 → 15.00, 100 → 8.00, 200 → 0.00."""

    zone = models.ForeignKey(DeliveryZone, on_delete=models.CASCADE, related_name="fee_tiers")
    from_value = models.DecimalField("Ab Warenwert (CHF)", **MONEY)
    fee = models.DecimalField("Liefergebühr (CHF)", **MONEY)

    class Meta:
        ordering = ["from_value"]
        constraints = [models.UniqueConstraint(fields=["zone", "from_value"], name="feetier_unique_threshold")]

    def __str__(self):
        return f"ab {self.from_value}: {self.fee}"
