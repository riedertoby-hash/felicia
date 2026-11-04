from django.core.management.base import BaseCommand

from apps.billing import services
from apps.core.models import Tenant


class Command(BaseCommand):
    help = "Täglich ausführen: Sammelrechnungen (Monat/Quartal) und Provisionsrechnungen für abgeschlossene Perioden."

    def handle(self, *args, **opts):
        invoices = services.run_periodic_invoicing()
        commissions = []
        for tenant in Tenant.objects.filter(is_active=True):
            commissions += services.run_commission_invoicing(tenant)
        from apps.billing.dunning import run_reminders

        reminders = run_reminders()
        self.stdout.write(
            f"{len(invoices)} Kundenrechnungen, {len(commissions)} Provisionsrechnungen erstellt, "
            f"{len(reminders)} Mahnungen versendet."
        )
