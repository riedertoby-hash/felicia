from django.core.management.base import BaseCommand

from apps.orders import standing


class Command(BaseCommand):
    help = "Alle 15 Minuten ausführen: löst fällige Daueraufträge kurz vor dem Bestellschluss als Bestellung aus."

    def handle(self, *args, **opts):
        created, problems = standing.run()
        self.stdout.write(f"{len(created)} Bestellungen aus Daueraufträgen, {len(problems)} Probleme.")
