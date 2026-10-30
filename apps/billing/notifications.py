import logging

from django.core.mail import EmailMessage

from .models import Invoice

logger = logging.getLogger(__name__)


def send_invoice(invoice_id):
    from .pdf import invoice_pdf

    invoice = Invoice.objects.select_related("issuer", "recipient").get(pk=invoice_id)
    to = invoice.recipient_snapshot.get("email")
    if not to:
        logger.warning("Rechnung %s: keine E-Mail-Adresse beim Empfänger", invoice.number)
        return
    try:
        message = EmailMessage(
            subject=f"Rechnung {invoice.number} von {invoice.issuer_snapshot.get('name')}",
            body=(
                f"Guten Tag\n\nIm Anhang finden Sie die Rechnung {invoice.number} über CHF {invoice.total}, "
                f"zahlbar bis {invoice.due_date:%d.%m.%Y}.\n\nFreundliche Grüsse\n"
                f"{invoice.issuer_snapshot.get('name')}"
            ),
            to=[to],
            reply_to=[invoice.issuer_snapshot["email"]] if invoice.issuer_snapshot.get("email") else None,
        )
        message.attach(f"Rechnung-{invoice.number}.pdf", invoice_pdf(invoice), "application/pdf")
        message.send()
    except Exception:  # noqa: BLE001 - a mail problem must never break invoicing
        logger.exception("Rechnung %s konnte nicht versendet werden", invoice.number)
