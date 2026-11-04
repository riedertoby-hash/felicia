import io
import logging

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def render_pdf(template, context):
    import weasyprint

    html = render_to_string(template, context)
    return weasyprint.HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()


def qr_bill_svg(invoice, amount=None, info=None):
    """Swiss QR-bill payment part as inline SVG, or None if creditor data is incomplete."""
    from qrbill import QRBill

    issuer, recipient = invoice.issuer_snapshot, invoice.recipient_snapshot
    if not (issuer.get("iban") and issuer.get("zip") and issuer.get("city")):
        return None
    try:
        bill = QRBill(
            account=issuer["iban"],
            creditor={
                "name": issuer["name"][:70],
                "line1": issuer.get("street", "")[:70],
                "line2": f"{issuer['zip']} {issuer['city']}"[:70],
                "country": "CH",
            },
            debtor={
                "name": recipient["name"][:70],
                "line1": recipient.get("street", "")[:70],
                "line2": f"{recipient.get('zip', '')} {recipient.get('city', '')}".strip()[:70],
                "country": "CH",
            }
            if recipient.get("city")
            else None,
            amount=f"{(invoice.total if amount is None else amount):.2f}",
            reference_number=invoice.reference,
            additional_information=info or f"Rechnung {invoice.number}",
            language="de",
        )
        buf = io.StringIO()
        bill.as_svg(buf, full_page=False)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - invoice must still render without the payment part
        logger.exception("QR-Rechnung für %s konnte nicht erzeugt werden", invoice.number)
        return None


def invoice_pdf(invoice):
    from apps.orders.models import Order

    return render_pdf(
        "documents/invoice.html",
        {
            "invoice": invoice,
            "lines": invoice.lines.all(),
            "qr_svg": qr_bill_svg(invoice),
            "orders": Order.objects.filter(invoice=invoice),
        },
    )
