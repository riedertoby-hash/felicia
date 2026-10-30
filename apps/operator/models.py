from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel
from apps.orgs.permissions import DEFAULT_MFA_REQUIRED_ROLES

PERCENT = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


def default_mfa_roles():
    return list(DEFAULT_MFA_REQUIRED_ROLES)


class MarketplaceSettings(TimeStampedModel):
    tenant = models.OneToOneField("core.Tenant", on_delete=models.CASCADE, related_name="settings")
    contact_email = models.EmailField("Kontakt-E-Mail", blank=True)
    default_commission_percent = models.DecimalField(
        "Provision Standard (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=PERCENT,
        help_text="Anteil vom Kundenpreis, den der Marktplatz einbehält.",
    )
    base_fee_enabled = models.BooleanField("Grundgebühr verrechnen", default=False)
    base_fee_monthly = models.DecimalField(
        "Grundgebühr pro Monat (CHF)",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    supplier_approval_required = models.BooleanField("Neue Lieferanten müssen freigeschaltet werden", default=True)
    mfa_required_roles = models.JSONField("2FA-Pflicht für Rollen", default=default_mfa_roles, blank=True)

    class Meta:
        verbose_name = "Marktplatz-Einstellungen"
        verbose_name_plural = "Marktplatz-Einstellungen"

    def __str__(self):
        return f"Einstellungen {self.tenant}"

    @classmethod
    def for_tenant(cls, tenant):
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj


class SupplierTerms(TimeStampedModel):
    """Commercial terms the operator sets per supplier. Suppliers can see but never edit them."""

    organization = models.OneToOneField("orgs.Organization", on_delete=models.CASCADE, related_name="terms")
    commission_percent = models.DecimalField(
        "Provision (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=PERCENT,
        help_text="Leer = Standard des Marktplatzes",
    )
    base_fee_monthly = models.DecimalField(
        "Grundgebühr pro Monat (CHF)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Leer = Standard des Marktplatzes",
    )
    internal_note = models.TextField("Interne Notiz", blank=True)

    class Meta:
        verbose_name = "Lieferanten-Konditionen"
        verbose_name_plural = "Lieferanten-Konditionen"

    def effective_commission(self):
        if self.commission_percent is not None:
            return self.commission_percent
        return MarketplaceSettings.for_tenant(self.organization.tenant).default_commission_percent

    def effective_base_fee(self):
        settings = MarketplaceSettings.for_tenant(self.organization.tenant)
        if not settings.base_fee_enabled:
            return Decimal("0.00")
        return self.base_fee_monthly if self.base_fee_monthly is not None else settings.base_fee_monthly
