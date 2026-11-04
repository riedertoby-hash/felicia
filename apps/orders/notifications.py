"""Order notifications. E-mail and webhook are implemented; SMS/push fall back to e-mail for now."""

import hashlib
import hmac
import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail import EmailMessage, send_mail
from django.template.loader import render_to_string

from .models import Order

logger = logging.getLogger(__name__)


def supplier_email(profile):
    return profile.notify_email or profile.contact_email


def webhook_secret(supplier):
    return hmac.new(settings.SECRET_KEY.encode(), f"webhook:{supplier.pk}".encode(), hashlib.sha256).hexdigest()


def order_payload(order):
    return {
        "event": "order.created",
        "number": order.number,
        "status": order.status,
        "customer": order.customer.name,
        "delivery": {
            "kind": order.delivery_kind,
            "date": str(order.delivery_date),
            "name": order.ship_name,
            "street": order.ship_street,
            "zip": order.ship_zip,
            "city": order.ship_city,
        },
        "lines": [
            {
                "sku": line.sku,
                "product": line.product_name,
                "variant": line.variant_name,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "unit_price": str(line.unit_price),
            }
            for line in order.lines.all()
        ],
        "goods_total": str(order.goods_total),
        "delivery_fee": str(order.delivery_fee),
        "total": str(order.total),
        "note": order.customer_note,
    }


def send_webhook(order):
    profile = order.supplier.supplier_profile
    if not profile.webhook_url.startswith("https://"):
        raise ValueError("Webhook nur über https")
    body = json.dumps(order_payload(order)).encode()
    signature = hmac.new(webhook_secret(order.supplier).encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(  # noqa: S310 - scheme checked above
        profile.webhook_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Felicia-Signature": f"sha256={signature}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - https enforced in form
        resp.read()


def notify_new_orders(order_ids):
    for order in Order.objects.filter(pk__in=order_ids).select_related(
        "supplier__supplier_profile", "customer", "placed_by"
    ):
        try:
            _notify_supplier(order)
        except Exception:  # noqa: BLE001
            logger.exception("Lieferant zu Bestellung %s konnte nicht benachrichtigt werden", order.number)
    orders = list(Order.objects.filter(pk__in=order_ids).select_related("supplier", "placed_by"))
    if orders and orders[0].placed_by:
        try:
            send_mail(
                subject="Ihre Bestellung ist eingegangen",
                message=render_to_string("orders/email/customer_confirmation.txt", {"orders": orders}),
                from_email=None,
                recipient_list=[orders[0].placed_by.email],
            )
        except Exception:  # noqa: BLE001
            logger.exception("Bestellbestätigung konnte nicht versendet werden")


def _notify_supplier(order):
    profile = order.supplier.supplier_profile
    if profile.notify_mode == "daily":
        return
    if profile.notify_channel == "webhook" and profile.webhook_url:
        try:
            send_webhook(order)
            return
        except Exception:  # noqa: BLE001
            logger.exception("Webhook für %s fehlgeschlagen, sende E-Mail", order.number)
    to = supplier_email(profile)
    if to:
        send_mail(
            subject=f"Neue Bestellung {order.number} von {order.customer.name}",
            message=render_to_string("orders/email/supplier_new_order.txt", {"order": order}),
            from_email=None,
            recipient_list=[to],
        )


def notify_status_change(order_id, old_status):
    order = Order.objects.select_related("placed_by", "supplier").get(pk=order_id)
    if order.status not in ("confirmed", "cancelled") or not order.placed_by:
        return
    try:
        send_mail(
            subject=f"Bestellung {order.number}: {order.get_status_display()}",
            message=render_to_string("orders/email/customer_status.txt", {"order": order}),
            from_email=None,
            recipient_list=[order.placed_by.email],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Statusmeldung %s konnte nicht versendet werden", order.number)


def send_daily_digest(supplier, orders, picking_pdf):
    profile = supplier.supplier_profile
    to = supplier_email(profile)
    if not to:
        return False
    message = EmailMessage(
        subject=f"Tagesübersicht: {len(orders)} neue Bestellung{'en' if len(orders) != 1 else ''}",
        body=render_to_string("orders/email/supplier_digest.txt", {"orders": orders, "supplier": supplier}),
        to=[to],
    )
    if picking_pdf:
        message.attach("Kommissionierliste.pdf", picking_pdf, "application/pdf")
    message.send()
    return True
