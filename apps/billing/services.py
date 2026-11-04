"""Invoicing. Suppliers invoice their customers (per order, monthly, quarterly or manually);
the operator invoices each supplier for its commission (and optional base fee)."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import log
from apps.catalog.models import VatRate
from apps.operator.models import MarketplaceSettings, SupplierTerms
from apps.orders.models import Order
from apps.orgs.models import Organization

from .models import BillingSettings, CustomerTerms, Invoice, InvoiceLine, InvoiceMode
from .reference import creditor_reference

CENT = Decimal("0.01")
MONTHS_DE = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


# --- periods ---------------------------------------------------------------------------------------


def month_bounds(day):
    start = day.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


def quarter_bounds(day):
    first_month = 3 * ((day.month - 1) // 3) + 1
    start = date(day.year, first_month, 1)
    end = date(day.year + (first_month + 3 > 12), (first_month + 2) % 12 + 1, 1) - timedelta(days=1)
    return start, end


def period_label(start, end):
    if start.month == end.month:
        return f"{MONTHS_DE[start.month - 1]} {start.year}"
    return f"Q{(start.month - 1) // 3 + 1} {start.year}"


def last_closed_period(mode, today):
    """The most recent fully finished month/quarter before today."""
    if mode == InvoiceMode.MONTHLY or mode == "monthly":
        return month_bounds(today.replace(day=1) - timedelta(days=1))
    start, _ = quarter_bounds(today)
    return quarter_bounds(start - timedelta(days=1))


# --- snapshots -------------------------------------------------------------------------------------


def supplier_snapshot(org):
    p = org.supplier_profile
    return {
        "name": p.legal_name or org.name,
        "street": p.street,
        "zip": p.zip_code,
        "city": p.city,
        "iban": p.iban or "",
        "vat_number": p.vat_number if p.vat_registered else "",
        "vat_registered": p.vat_registered,
        "email": p.contact_email,
        "phone": p.phone,
    }


def customer_snapshot(org):
    p = org.customer_profile
    return {
        "name": p.billing_name or org.name,
        "street": p.billing_street,
        "zip": p.billing_zip_code,
        "city": p.billing_city,
        "email": p.billing_email,
    }


def operator_snapshot(tenant):
    s = MarketplaceSettings.for_tenant(tenant)
    return {
        "name": s.legal_name or tenant.name,
        "street": s.street,
        "zip": s.zip_code,
        "city": s.city,
        "iban": s.iban or "",
        "vat_number": s.vat_number if s.vat_registered else "",
        "vat_registered": s.vat_registered,
        "email": s.contact_email,
    }


def supplier_as_recipient(org):
    snap = supplier_snapshot(org)
    return {k: snap[k] for k in ("name", "street", "zip", "city", "email")}


# --- VAT -------------------------------------------------------------------------------------------


def vat_of(gross, rate):
    """Prices are gross (incl. VAT). VAT share = gross × rate / (100 + rate)."""
    rate = Decimal(rate)
    return (gross * rate / (100 + rate)).quantize(CENT, rounding=ROUND_HALF_UP) if rate else Decimal("0")


def finalize_totals(invoice, vat_registered):
    groups = defaultdict(Decimal)
    for line in invoice.lines.all():
        groups[line.vat_rate if vat_registered else "0"] += line.total
    invoice.total = sum(groups.values(), Decimal("0"))
    breakdown = []
    for rate, gross in sorted(groups.items(), key=lambda x: Decimal(x[0])):
        vat = vat_of(gross, rate)
        if Decimal(rate):
            breakdown.append([rate, str(gross - vat), str(vat)])
    invoice.vat_breakdown = breakdown
    invoice.vat_total = sum((Decimal(b[2]) for b in breakdown), Decimal("0"))
    invoice.save(update_fields=["total", "vat_total", "vat_breakdown"])


def dominant_rate(order):
    """Delivery fee follows the VAT rate of most of the goods (ancillary service)."""
    totals = defaultdict(Decimal)
    for line in order.lines.all():
        totals[line.vat_rate] += line.line_total
    return max(totals, key=totals.get) if totals else VatRate.REDUCED


# --- customer invoices -----------------------------------------------------------------------------


def effective_terms(supplier, customer):
    settings = BillingSettings.for_org(supplier)
    terms = CustomerTerms.objects.filter(supplier=supplier, customer=customer).first()
    mode = terms.invoice_mode if terms and terms.invoice_mode else settings.invoice_mode
    days = terms.payment_terms_days if terms and terms.payment_terms_days is not None else settings.payment_terms_days
    return mode, days, settings.footer


def invoiceable_orders(supplier, customer=None, until=None):
    qs = Order.objects.filter(supplier=supplier, status=Order.Status.DELIVERED, invoice__isnull=True)
    if customer is not None:
        qs = qs.filter(customer=customer)
    if until is not None:
        qs = qs.filter(delivery_date__lte=until)
    return qs.order_by("delivery_date", "number")


@transaction.atomic
def create_sale_invoice(*, supplier, customer, orders, period=None, request=None):
    orders = list(
        Order.objects.select_for_update()
        .filter(
            pk__in=[o.pk for o in orders],
            supplier=supplier,
            customer=customer,
            status="delivered",
            invoice__isnull=True,
        )
        .order_by("delivery_date")
    )
    if not orders:
        raise ValidationError("Keine verrechenbaren Bestellungen (geliefert und noch nicht verrechnet).")
    _, days, footer = effective_terms(supplier, customer)
    issuer = supplier_snapshot(supplier)
    number = Invoice.next_number(supplier)
    today = timezone.localdate()
    invoice = Invoice.objects.create(
        tenant=supplier.tenant,
        kind=Invoice.Kind.SALE,
        issuer=supplier,
        recipient=customer,
        number=number,
        reference=creditor_reference(f"{supplier.pk}X{number}"),
        issue_date=today,
        due_date=today + timedelta(days=days),
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        total=0,
        issuer_snapshot=issuer,
        recipient_snapshot=customer_snapshot(customer),
        footer=footer,
    )
    lines, sort = [], 0
    for order in orders:
        head = f"Bestellung {order.number} vom {order.created_at:%d.%m.%Y}, geliefert {order.delivery_date:%d.%m.%Y}"
        lines.append(
            InvoiceLine(invoice=invoice, order=order, description=head, quantity=0, unit_price=0, total=0, sort=sort)
        )
        sort += 1
        for line in order.lines.all():
            lines.append(
                InvoiceLine(
                    invoice=invoice,
                    order=order,
                    description=f"{line.product_name} {line.variant_name}",
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=line.unit_price,
                    vat_rate=line.vat_rate,
                    total=line.line_total,
                    sort=sort,
                )
            )
            sort += 1
        if order.delivery_fee:
            lines.append(
                InvoiceLine(
                    invoice=invoice,
                    order=order,
                    description=f"Lieferung ({order.delivery_name})",
                    unit_price=order.delivery_fee,
                    vat_rate=dominant_rate(order),
                    total=order.delivery_fee,
                    sort=sort,
                )
            )
            sort += 1
    InvoiceLine.objects.bulk_create(lines)
    finalize_totals(invoice, issuer["vat_registered"])
    Order.objects.filter(pk__in=[o.pk for o in orders]).update(invoice=invoice)
    log(
        "invoice.created",
        request=request,
        organization=supplier,
        target=invoice,
        changes={"kunde": customer.name, "total": str(invoice.total), "bestellungen": len(orders)},
    )
    from .notifications import send_invoice

    transaction.on_commit(lambda: send_invoice(invoice.pk))
    return invoice


def invoice_on_delivery(order):
    mode, _, _ = effective_terms(order.supplier, order.customer)
    if mode == InvoiceMode.PER_ORDER:
        return create_sale_invoice(supplier=order.supplier, customer=order.customer, orders=[order])
    return None


def run_periodic_invoicing(today=None):
    """Daily job: collective invoices for every closed month/quarter. Safe to run repeatedly."""
    today = today or timezone.localdate()
    created = []
    pairs = (
        Order.objects.filter(status="delivered", invoice__isnull=True)
        .values_list("supplier_id", "customer_id")
        .distinct()
    )
    for supplier_id, customer_id in pairs:
        supplier = Organization.objects.get(pk=supplier_id)
        customer = Organization.objects.get(pk=customer_id)
        mode, _, _ = effective_terms(supplier, customer)
        if mode not in (InvoiceMode.MONTHLY, InvoiceMode.QUARTERLY):
            continue
        period = last_closed_period(mode, today)
        orders = list(invoiceable_orders(supplier, customer, until=period[1]))
        if orders:
            created.append(create_sale_invoice(supplier=supplier, customer=customer, orders=orders, period=period))
    return created


# --- commission invoices ---------------------------------------------------------------------------


@transaction.atomic
def create_commission_invoice(*, supplier, period, request=None):
    tenant = supplier.tenant
    operator = Organization.objects.filter(tenant=tenant, kind="operator").first()
    if operator is None:
        return None
    if Invoice.objects.filter(kind="commission", issuer=operator, recipient=supplier, period_start=period[0]).exists():
        return None
    orders = Order.objects.filter(supplier=supplier, status="delivered", delivery_date__range=period)
    terms = SupplierTerms.objects.filter(organization=supplier).first()
    settings = MarketplaceSettings.for_tenant(tenant)
    lines = []
    by_rate = defaultdict(lambda: [Decimal("0"), 0])
    for order in orders:
        entry = by_rate[order.commission_percent]
        entry[0] += order.goods_total
        entry[1] += 1
    label = period_label(*period)
    for percent, (goods, count) in sorted(by_rate.items()):
        commission = (goods * percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        lines.append(
            (
                f"Provision {percent.normalize()} % auf Warenumsatz {label} "
                f"({count} Bestellung{'en' if count != 1 else ''}, CHF {goods})",
                commission,
            )
        )
    months = 1 if period[0].month == period[1].month else 3
    base_fee = terms.effective_base_fee() if terms else Decimal("0")
    if base_fee:
        lines.append((f"Grundgebühr {label} ({months} × CHF {base_fee})", base_fee * months))
    if not lines:
        return None
    issuer = operator_snapshot(tenant)
    number = Invoice.next_number(operator)
    today = timezone.localdate()
    invoice = Invoice.objects.create(
        tenant=tenant,
        kind=Invoice.Kind.COMMISSION,
        issuer=operator,
        recipient=supplier,
        number=number,
        reference=creditor_reference(f"{operator.pk}X{number}"),
        issue_date=today,
        due_date=today + timedelta(days=30),
        period_start=period[0],
        period_end=period[1],
        total=0,
        issuer_snapshot=issuer,
        recipient_snapshot=supplier_as_recipient(supplier),
    )
    rate = "8.1" if settings.vat_registered else "0"
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(invoice=invoice, description=text, unit_price=amount, vat_rate=rate, total=amount, sort=i)
            for i, (text, amount) in enumerate(lines)
        ]
    )
    finalize_totals(invoice, settings.vat_registered)
    log(
        "invoice.created",
        request=request,
        organization=supplier,
        target=invoice,
        changes={"art": "Provision", "total": str(invoice.total), "periode": label},
    )
    from .notifications import send_invoice

    transaction.on_commit(lambda: send_invoice(invoice.pk))
    return invoice


def run_commission_invoicing(tenant, today=None):
    today = today or timezone.localdate()
    settings = MarketplaceSettings.for_tenant(tenant)
    period = last_closed_period(settings.commission_period, today)
    created = []
    for supplier in Organization.objects.filter(tenant=tenant, kind="supplier").exclude(status="pending"):
        invoice = create_commission_invoice(supplier=supplier, period=period)
        if invoice:
            created.append(invoice)
    return created


# --- payments --------------------------------------------------------------------------------------


def set_paid(*, invoice, paid, request):
    old = invoice.status
    if invoice.status == Invoice.Status.CANCELLED:
        raise ValidationError("Stornierte Rechnungen können nicht bezahlt werden.")
    invoice.status = Invoice.Status.PAID if paid else Invoice.Status.OPEN
    invoice.paid_at = timezone.localdate() if paid else None
    invoice.save(update_fields=["status", "paid_at", "updated_at"])
    log(
        "invoice.paid" if paid else "invoice.unpaid",
        request=request,
        organization=invoice.issuer,
        target=invoice,
        changes={"status": [old, invoice.status]},
    )


@transaction.atomic
def cancel_invoice(*, invoice, request):
    if invoice.status == Invoice.Status.PAID:
        raise ValidationError("Bezahlte Rechnungen können nicht storniert werden.")
    invoice.status = Invoice.Status.CANCELLED
    invoice.save(update_fields=["status", "updated_at"])
    Order.objects.filter(invoice=invoice).update(invoice=None)  # orders become invoiceable again
    log("invoice.cancelled", request=request, organization=invoice.issuer, target=invoice)


def open_amount(qs):
    return qs.filter(status=Invoice.Status.OPEN).aggregate(s=Sum("total"))["s"] or Decimal("0")
