from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Tenant
from apps.orgs.models import Membership, Organization, Role
from apps.orgs.services import create_organization

PASSWORD = "Demo-Passwort-2026!"
SUPPLIERS = [
    ("Hof Sonnenberg", "Liestal", "4410", "BL", "active"),
    ("Käserei Jura", "Laufen", "4242", "BL", "active"),
    ("Gemüse Leimental", "Therwil", "4106", "BL", "pending"),
]
CUSTOMERS = [("Restaurant Linde", "Basel", "4051"), ("Kantine Rheinhafen", "Basel", "4057")]


class Command(BaseCommand):
    help = "Legt Demodaten an (nur Entwicklung). Passwort für alle: " + PASSWORD

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Nur mit DJANGO_DEBUG=1 erlaubt.")
        tenant = Tenant.objects.get(slug=settings.DEFAULT_TENANT_SLUG)
        User = get_user_model()

        def user(email, first, last):
            u, created = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last})
            if created:
                u.set_password(PASSWORD)
                u.save()
                EmailAddress.objects.create(user=u, email=email, verified=True, primary=True)
            return u

        for i, (name, city, zip_code, canton, status) in enumerate(SUPPLIERS, 1):
            if Organization.objects.filter(tenant=tenant, name=name).exists():
                continue
            owner = user(f"lieferant{i}@demo.ch", "Inhaber", name.split()[-1])
            org = create_organization(tenant=tenant, kind="supplier", name=name, owner=owner)
            org.status = status
            org.save()
            p = org.supplier_profile
            p.city, p.zip_code, p.canton, p.street = city, zip_code, canton, "Dorfstrasse 1"
            p.description = f"Regionale Produkte von {name}."
            p.save()
            clerk = user(f"mitarbeiter{i}@demo.ch", "Mitarbeiter", name.split()[-1])
            Membership.objects.create(user=clerk, organization=org, role=Role.objects.get(key="supplier_clerk"))

        for i, (name, city, zip_code) in enumerate(CUSTOMERS, 1):
            if Organization.objects.filter(tenant=tenant, name=name).exists():
                continue
            owner = user(f"kunde{i}@demo.ch", "Chef", name.split()[-1])
            org = create_organization(tenant=tenant, kind="customer", name=name, owner=owner, customer_type="business")
            p = org.customer_profile
            p.billing_street, p.billing_zip_code, p.billing_city = "Hauptstrasse 5", zip_code, city
            p.save()
        self.stdout.write(self.style.SUCCESS(f"Demodaten bereit. Passwort: {PASSWORD}"))
