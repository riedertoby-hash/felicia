from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing.pdf import render_pdf
from apps.orders import documents
from apps.orders.models import Order
from apps.orders.notifications import send_daily_digest
from apps.suppliers.models import SupplierProfile


class Command(BaseCommand):
    help = "Alle 15 Minuten ausführen: verschickt den Tageszusammenzug an Lieferanten, deren Uhrzeit erreicht ist."

    def handle(self, *args, **opts):
        now = timezone.localtime()
        sent = 0
        profiles = SupplierProfile.objects.filter(
            notify_mode__in=["daily", "both"], organization__status="active"
        ).select_related("organization")
        for profile in profiles:
            if profile.last_digest_on == now.date() or now.time() < profile.notify_digest_time:
                continue
            since = (
                timezone.make_aware(datetime.combine(profile.last_digest_on or now.date(), time.min))
                if profile.last_digest_on
                else now.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            orders = list(
                Order.objects.filter(supplier=profile.organization, created_at__gte=since)
                .select_related("customer")
                .prefetch_related("lines")
                .order_by("delivery_date")
            )
            if orders:
                pdf = render_pdf(
                    "documents/picking_list.html",
                    {
                        "day": None,
                        "supplier": profile.organization,
                        "orders": orders,
                        "picking": documents.picking_list(orders),
                    },
                )
                if send_daily_digest(profile.organization, orders, pdf):
                    sent += 1
            profile.last_digest_on = now.date()
            profile.save(update_fields=["last_digest_on"])
        self.stdout.write(f"{sent} Tageszusammenzüge versendet.")
