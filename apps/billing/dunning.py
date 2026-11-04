"""Payment reminders: Zahlungserinnerung → 1. Mahnung → 2. Mahnung, each with a fresh QR payment part."""

import logging
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log

from .models import BillingSettings, Invoice, Reminder

logger = logging.getLogger(__name__)


def next_due_date(invoice, settings):
    """Date on which the next reminder is due, or None if no further reminder applies."""
    if invoice.status != Invoice.Status.OPEN or invoice.reminder_level >= settings.max_reminder_level:
        return None
    if invoice.reminder_level == 0:
        return invoice.due_date + timedelta(days=settings.first_reminder_days)
    return (invoice.last_reminder_on or invoice.due_date) + timedelta(days=settings.reminder_interval_days)


@transaction.atomic
def send_reminder(invoice, *, request=None, manual=False, today=None):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.OPEN:
        raise ValidationError("Nur offene Rechnungen können gemahnt werden.")
    settings = BillingSettings.for_org(invoice.issuer)
    if invoice.reminder_level >= 3:
        raise ValidationError("Die höchste Mahnstufe ist erreicht.")
    level = invoice.reminder_level + 1
    fee = settings.reminder_fee if level >= 2 else Decimal("0")
    invoice.reminder_level = level
    today = today or timezone.localdate()
    invoice.last_reminder_on = today
    invoice.fees_total += fee
    invoice.save(update_fields=["reminder_level", "last_reminder_on", "fees_total", "updated_at"])
    reminder = Reminder.objects.create(
        invoice=invoice, level=level, fee=fee, amount_due=invoice.amount_due, manual=manual, sent_on=today
    )
    log(
        "invoice.reminder",
        request=request,
        organization=invoice.issuer,
        target=invoice,
        changes={"stufe": invoice.reminder_label, "gebühr": str(fee), "offen": str(invoice.amount_due)},
    )
    transaction.on_commit(lambda: _email(reminder.pk))
    return reminder


def run_reminders(today=None):
    """Daily job: send all reminders that are due."""
    today = today or timezone.localdate()
    sent = []
    for invoice in Invoice.objects.filter(status="open", due_date__lt=today).select_related("issuer"):
        settings = BillingSettings.for_org(invoice.issuer)
        if not settings.reminders_enabled:
            continue
        due = next_due_date(invoice, settings)
        if due is not None and due <= today:
            sent.append(send_reminder(invoice, today=today))
    return sent


def reminder_pdf(reminder):
    from .pdf import qr_bill_svg, render_pdf

    invoice = reminder.invoice
    return render_pdf(
        "documents/reminder.html",
        {
            "reminder": reminder,
            "invoice": invoice,
            "qr_svg": qr_bill_svg(
                invoice,
                amount=reminder.amount_due,
                info=f"{invoice.REMINDER_LABELS[reminder.level]} Rechnung {invoice.number}",
            ),
        },
    )


def _email(reminder_id):
    reminder = Reminder.objects.select_related("invoice").get(pk=reminder_id)
    invoice = reminder.invoice
    to = invoice.recipient_snapshot.get("email")
    if not to:
        logger.warning("Mahnung %s: keine E-Mail beim Empfänger", invoice.number)
        return
    label = Invoice.REMINDER_LABELS[reminder.level]
    try:
        message = EmailMessage(
            subject=f"{label}: Rechnung {invoice.number} von {invoice.issuer_snapshot.get('name')}",
            body=(
                f"Guten Tag\n\nUnsere Rechnung {invoice.number} vom {invoice.issue_date:%d.%m.%Y} war am "
                f"{invoice.due_date:%d.%m.%Y} fällig. Offen sind CHF {reminder.amount_due}"
                f"{f' (inkl. Mahngebühr CHF {reminder.fee})' if reminder.fee else ''}.\n\n"
                "Falls Sie bereits bezahlt haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.\n\n"
                f"Freundliche Grüsse\n{invoice.issuer_snapshot.get('name')}"
            ),
            to=[to],
            reply_to=[invoice.issuer_snapshot["email"]] if invoice.issuer_snapshot.get("email") else None,
        )
        message.attach(f"{label.replace(' ', '-')}-{invoice.number}.pdf", reminder_pdf(reminder), "application/pdf")
        message.send()
    except Exception:  # noqa: BLE001 - mail problems must not break the job
        logger.exception("Mahnung zu %s konnte nicht versendet werden", invoice.number)
