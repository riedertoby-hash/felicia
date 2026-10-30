from decimal import Decimal

from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import Sequence, TenantModel, TimeStampedModel

MONEY = {"max_digits": 10, "decimal_places": 2}


class InvoiceMode(models.TextChoices):
    PER_ORDER = "per_order", "Pro Bestellung (bei Lieferung)"
    MONTHLY = "monthly", "Sammelrechnung Ende Monat"
    QUARTERLY = "quarterly", "Sammelrechnung Ende Quartal"
    MANUAL = "manual", "Manuell"


class BillingSettings(TimeStampedModel):
    """How a supplier invoices its customers by default."""

    organization = models.OneToOneField("orgs.Organization", on_delete=models.CASCADE, related_name="billing")
    invoice_mode = models.CharField(
        "Rechnungsstellung", max_length=16, choices=InvoiceMode.choices, default=InvoiceMode.MONTHLY
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        "Zahlungsfrist (Tage)", default=30, validators=[MaxValueValidator(120)]
    )
    footer = models.TextField("Text auf der Rechnung", blank=True, help_text="z.B. Dank, Hinweise")

    class Meta:
        verbose_name = "Rechnungseinstellungen"

    @classmethod
    def for_org(cls, org):
        obj, _ = cls.objects.get_or_create(organization=org)
        return obj


class CustomerTerms(TimeStampedModel):
    """Supplier-specific deviations for one customer (e.g. this restaurant gets a quarterly invoice)."""

    supplier = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="customer_terms")
    customer = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="supplier_terms")
    invoice_mode = models.CharField(
        "Rechnungsstellung",
        max_length=16,
        choices=InvoiceMode.choices,
        blank=True,
        help_text="Leer = Ihre Standardeinstellung",
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        "Zahlungsfrist (Tage)", null=True, blank=True, validators=[MaxValueValidator(120)]
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["supplier", "customer"], name="customerterms_unique")]


class Invoice(TenantModel):
    class Kind(models.TextChoices):
        SALE = "sale", "Rechnung an Kunde"
        COMMISSION = "commission", "Provisionsrechnung"

    class Status(models.TextChoices):
        OPEN = "open", "Offen"
        PAID = "paid", "Bezahlt"
        CANCELLED = "cancelled", "Storniert"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    issuer = models.ForeignKey("orgs.Organization", on_delete=models.PROTECT, related_name="invoices_issued")
    recipient = models.ForeignKey("orgs.Organization", on_delete=models.PROTECT, related_name="invoices_received")
    number = models.CharField(max_length=24)
    reference = models.CharField("Zahlungsreferenz", max_length=27)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    paid_at = models.DateField(null=True, blank=True)
    total = models.DecimalField(**MONEY)
    vat_total = models.DecimalField(**MONEY, default=Decimal("0"))
    vat_breakdown = models.JSONField(default=list, blank=True)  # [[rate, base, vat], ...]
    issuer_snapshot = models.JSONField(default=dict)
    recipient_snapshot = models.JSONField(default=dict)
    footer = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["issuer", "number"], name="invoice_unique_number"),
            models.UniqueConstraint(
                fields=["kind", "issuer", "recipient", "period_start"],
                condition=models.Q(kind="commission"),
                name="commission_once_per_period",
            ),
        ]

    def __str__(self):
        return f"Rechnung {self.number}"

    @staticmethod
    def next_number(issuer):
        year = timezone.localdate().year
        return f"{year}-{Sequence.next(f'invoice:{issuer.pk}:{year}'):04d}"

    @property
    def is_overdue(self):
        return self.status == self.Status.OPEN and self.due_date < timezone.localdate()

    @property
    def net_total(self):
        return self.total - self.vat_total


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    unit = models.CharField(max_length=10, blank=True)
    unit_price = models.DecimalField(**MONEY)
    vat_rate = models.CharField(max_length=4, default="0")
    total = models.DecimalField(**MONEY)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "pk"]

    def __str__(self):
        return self.description
