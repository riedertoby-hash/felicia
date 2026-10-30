from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog import csv_import
from apps.catalog.defaults import seed_catalog_defaults
from apps.catalog.models import Label
from apps.core.models import Tenant
from apps.orgs.models import Membership, Organization, Role
from apps.orgs.services import create_organization

PASSWORD = "Demo-Passwort-2026!"
SUPPLIERS = [
    ("Hof Sonnenberg", "Liestal", "4410", "BL", "active"),
    ("Käserei Jura", "Laufen", "4242", "BL", "active"),
    ("Gemüse Leimental", "Therwil", "4106", "BL", "pending"),
]
PRODUCTS = {
    "Hof Sonnenberg": (
        "artikel;variante;einheit;kundenpreis;mwst;mindestmenge;kategorie;temperatur;haltbarkeit_tage;"
        "vorlaufzeit_tage;herkunft;artikelnummer;beschreibung\n"
        "Kartoffeln festkochend;2,5 kg;Kiste;9.50;2.6;1;Kartoffeln;ungekühlt;30;1;Liestal BL;HS-KAR-25;Sorte Agria\n"
        "Kartoffeln festkochend;10 kg;Kiste;32.00;2.6;1;Kartoffeln;ungekühlt;30;1;Liestal BL;HS-KAR-10;Sorte Agria\n"
        "Rüebli;1 kg;kg;3.80;2.6;2;Gemüse;ungekühlt;14;1;Liestal BL;HS-RUE-1;\n"
        "Kopfsalat;Stück;Stk;2.20;2.6;6;Salate;gekühlt;4;1;Liestal BL;HS-KS;Frisch geerntet\n"
        "Freilandeier;10 Stück;Packung;7.50;2.6;3;Eier;gekühlt;21;2;Liestal BL;HS-EI-10;\n"
        "Apfelsaft naturtrüb;1 l;Flasche;4.20;2.6;6;Säfte;ungekühlt;180;2;Liestal BL;HS-AS-1;Aus Hochstamm-Äpfeln\n"
    ),
    "Käserei Jura": (
        "artikel;variante;einheit;kundenpreis;mwst;mindestmenge;kategorie;temperatur;haltbarkeit_tage;"
        "vorlaufzeit_tage;herkunft;artikelnummer;beschreibung\n"
        "Bergkäse rezent;250 g;Stk;7.80;2.6;2;Käse;gekühlt;60;2;Laufen BL;KJ-BK-250;12 Monate gereift\n"
        "Bergkäse rezent;1 kg;kg;28.50;2.6;1;Käse;gekühlt;60;2;Laufen BL;KJ-BK-1000;12 Monate gereift\n"
        "Vollmilch;1 l;Flasche;1.90;2.6;12;Milch & Joghurt;gekühlt;7;1;Laufen BL;KJ-MI-1;Pastmilch\n"
        "Joghurt nature;180 g;Glas;1.60;2.6;12;Milch & Joghurt;gekühlt;21;1;Laufen BL;KJ-JO-180;\n"
        "Butter;250 g;Stk;4.90;2.6;4;Butter & Rahm;gekühlt;30;1;Laufen BL;KJ-BU-250;Vorzugsbutter\n"
        "Glacé Vanille;1 l;Packung;12.00;2.6;2;Milch & Joghurt;tiefgekühlt;180;3;Laufen BL;KJ-GL-1;\n"
    ),
}
CUSTOMERS = [("Restaurant Linde", "Basel", "4051"), ("Kantine Rheinhafen", "Basel", "4057")]


class Command(BaseCommand):
    help = "Legt Demodaten an (nur Entwicklung). Passwort für alle: " + PASSWORD

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Nur mit DJANGO_DEBUG=1 erlaubt.")
        tenant = Tenant.objects.get(slug=settings.DEFAULT_TENANT_SLUG)
        seed_catalog_defaults(tenant)
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

        for name, text in PRODUCTS.items():
            org = Organization.objects.get(tenant=tenant, name=name)
            if org.products.exists():
                continue
            rows, error = csv_import.parse(text, supplier=org)
            if error or any(r.errors for r in rows):
                raise CommandError(f"Demodaten fehlerhaft: {error or [r.errors for r in rows if r.errors]}")
            csv_import.apply(rows, supplier=org)
            bio = Label.objects.get(tenant=tenant, name="Bio Suisse")
            for product in org.products.all()[:3]:
                product.labels.add(bio)

        for i, (name, city, zip_code) in enumerate(CUSTOMERS, 1):
            if Organization.objects.filter(tenant=tenant, name=name).exists():
                continue
            owner = user(f"kunde{i}@demo.ch", "Chef", name.split()[-1])
            org = create_organization(tenant=tenant, kind="customer", name=name, owner=owner, customer_type="business")
            p = org.customer_profile
            p.billing_street, p.billing_zip_code, p.billing_city = "Hauptstrasse 5", zip_code, city
            p.save()
        self.stdout.write(self.style.SUCCESS(f"Demodaten bereit. Passwort: {PASSWORD}"))
