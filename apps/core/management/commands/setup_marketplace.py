from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Tenant
from apps.operator.models import MarketplaceSettings
from apps.orgs.models import Membership, Organization, Role


class Command(BaseCommand):
    help = "Legt den Marktplatz (Mandant), die Betreiber-Organisation und den ersten Super-Admin an."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="feldzutisch")
        parser.add_argument("--name", default="Feld zu Tisch")
        parser.add_argument("--domain", default="")
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--admin-password", help="Nur für Entwicklung; sonst per Passwort-Reset setzen.")

    @transaction.atomic
    def handle(self, *args, **opts):
        tenant, created = Tenant.objects.get_or_create(
            slug=opts["slug"], defaults={"name": opts["name"], "domain": opts["domain"]}
        )
        MarketplaceSettings.for_tenant(tenant)
        operator, _ = Organization.objects.get_or_create(
            tenant=tenant, kind=Organization.Kind.OPERATOR, defaults={"name": opts["name"]}
        )
        User = get_user_model()
        email = opts["admin_email"].lower()
        user, user_created = User.objects.get_or_create(email=email)
        if user_created:
            if opts["admin_password"]:
                user.set_password(opts["admin_password"])
            else:
                user.set_unusable_password()
            user.save()
            EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
        role = Role.objects.get(tenant__isnull=True, key="operator_admin")
        Membership.objects.get_or_create(user=user, organization=operator, defaults={"role": role})
        if not created and not user_created:
            raise CommandError("Mandant und Benutzer existieren bereits – nichts geändert.")
        self.stdout.write(self.style.SUCCESS(f"Marktplatz «{tenant.name}» bereit. Super-Admin: {email}"))
