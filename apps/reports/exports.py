"""CSV exports for accounting. Semicolon-separated, UTF-8 with BOM: opens directly in Excel and
can be imported into Bexio/Abacus (manual bookings / journal import)."""

import csv
import io
from decimal import Decimal

from django.http import HttpResponse

from apps.billing.models import BillingSettings, Invoice, Payment
from apps.billing.services import vat_of

from .services import orders_in


def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    response = HttpResponse(buf.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _invoices(org, period):
    return (
        Invoice.objects.filter(issuer=org, issue_date__range=(period.start, period.end))
        .exclude(status="cancelled")
        .select_related("recipient")
        .order_by("issue_date", "number")
    )


def invoice_list(org, period):
    rows = []
    for inv in _invoices(org, period):
        rows.append(
            [
                inv.number,
                f"{inv.issue_date:%d.%m.%Y}",
                f"{inv.due_date:%d.%m.%Y}",
                inv.recipient.name,
                inv.net_total,
                inv.vat_total,
                inv.total,
                inv.fees_total,
                inv.paid_amount,
                inv.get_status_display(),
                f"{inv.paid_at:%d.%m.%Y}" if inv.paid_at else "",
                inv.reference,
            ]
        )
    return csv_response(
        f"rechnungen-{period.start:%Y%m%d}-{period.end:%Y%m%d}.csv",
        [
            "Rechnung",
            "Datum",
            "Fällig",
            "Empfänger",
            "Netto",
            "MWST",
            "Brutto",
            "Mahngebühren",
            "Bezahlt",
            "Status",
            "Bezahlt am",
            "Referenz",
        ],
        rows,
    )


def journal(org, period):
    """Double-entry booking lines: invoices (debtors / revenue per VAT rate), fees and payments."""
    s = BillingSettings.for_org(org)
    rows = []
    for inv in _invoices(org, period):
        text = f"Rechnung {inv.number} {inv.recipient.name}"
        rates = {}
        for line in inv.lines.all():
            if line.total:
                rate = line.vat_rate if inv.issuer_snapshot.get("vat_registered") else "0"
                rates[rate] = rates.get(rate, Decimal("0")) + line.total
        for rate, gross in sorted(rates.items()):
            rows.append(
                [
                    f"{inv.issue_date:%d.%m.%Y}",
                    inv.number,
                    s.account_debtors,
                    s.account_revenue,
                    gross,
                    rate if Decimal(rate) else "",
                    vat_of(gross, rate),
                    text,
                ]
            )
        if inv.fees_total:
            rows.append(
                [
                    f"{(inv.last_reminder_on or inv.issue_date):%d.%m.%Y}",
                    inv.number,
                    s.account_debtors,
                    s.account_fees,
                    inv.fees_total,
                    "",
                    Decimal("0"),
                    f"Mahngebühren {inv.number}",
                ]
            )
    payments = (
        Payment.objects.filter(organization=org, booked_on__range=(period.start, period.end))
        .select_related("invoice")
        .order_by("booked_on")
    )
    for p in payments:
        if p.status == "unmatched":
            continue
        rows.append(
            [
                f"{p.booked_on:%d.%m.%Y}",
                p.invoice.number if p.invoice else "",
                s.account_bank,
                s.account_debtors,
                p.amount,
                "",
                Decimal("0"),
                f"Zahlung {p.debtor or ''} {p.invoice.number if p.invoice else ''}".strip(),
            ]
        )
    return csv_response(
        f"buchungsjournal-{period.start:%Y%m%d}-{period.end:%Y%m%d}.csv",
        ["Datum", "Beleg", "Soll", "Haben", "Betrag", "MWST-Satz", "MWST-Betrag", "Text"],
        rows,
    )


def sales_lines(period, **filters):
    rows = []
    orders = orders_in(period, **filters).select_related("customer", "supplier").prefetch_related("lines")
    for o in orders.order_by("delivery_date", "number"):
        for line in o.lines.all():
            rows.append(
                [
                    o.number,
                    f"{o.delivery_date:%d.%m.%Y}",
                    o.supplier.name,
                    o.customer.name,
                    line.product_name,
                    line.variant_name,
                    line.sku,
                    line.quantity,
                    line.unit,
                    line.unit_price,
                    line.line_total,
                    line.vat_rate,
                    o.commission_percent,
                ]
            )
    return csv_response(
        f"umsatz-{period.start:%Y%m%d}-{period.end:%Y%m%d}.csv",
        [
            "Bestellung",
            "Liefertermin",
            "Lieferant",
            "Kunde",
            "Artikel",
            "Variante",
            "Art.-Nr.",
            "Menge",
            "Einheit",
            "Preis",
            "Total",
            "MWST",
            "Provision %",
        ],
        rows,
    )
