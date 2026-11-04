"""Price logic. The customer price is stored; what the supplier receives is derived from the
operator's commission, so suppliers can work in either direction but never change the commission."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
FIVE_RAPPEN = Decimal("0.05")
HUNDRED = Decimal("100")


def round_5_rappen(amount):
    return (Decimal(amount) / FIVE_RAPPEN).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * FIVE_RAPPEN


def supplier_net(customer_price, commission_percent):
    """What the supplier receives for one unit."""
    share = Decimal(1) - Decimal(commission_percent) / HUNDRED
    return (Decimal(customer_price) * share).quantize(CENT, rounding=ROUND_HALF_UP)


def commission_amount(customer_price, commission_percent):
    return Decimal(customer_price) - supplier_net(customer_price, commission_percent)


def customer_price_from_supplier(supplier_price, commission_percent):
    """Customer price that gives the supplier (about) the wished amount, rounded to 5 Rappen."""
    share = Decimal(1) - Decimal(commission_percent) / HUNDRED
    if share <= 0:
        raise ValueError("Provision muss unter 100 % liegen.")
    return round_5_rappen(Decimal(supplier_price) / share)


def commission_for(supplier):
    """Effective commission for a supplier organization."""
    from apps.operator.models import MarketplaceSettings, SupplierTerms

    terms = SupplierTerms.objects.filter(organization=supplier).first()
    if terms is not None:
        return terms.effective_commission()
    return MarketplaceSettings.for_tenant(supplier.tenant).default_commission_percent
