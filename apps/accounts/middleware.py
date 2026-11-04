from allauth.mfa.utils import is_mfa_enabled
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

ALLOWED_PREFIXES = ("/konto/", "/static/", "/media/", "/healthz")


class EnforceMfaMiddleware:
    """Users whose role requires 2FA (set by the operator) must set it up before doing anything else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and not request.path.startswith(ALLOWED_PREFIXES)
            and requires_mfa(request)
            and not is_mfa_enabled(user)
        ):
            messages.warning(request, "Für Ihre Rolle ist die Zwei-Faktor-Anmeldung Pflicht. Bitte jetzt einrichten.")
            return redirect(reverse("mfa_index"))
        return self.get_response(request)


def requires_mfa(request):
    user = request.user
    if user.is_superuser:
        return True
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return False
    from apps.operator.models import MarketplaceSettings
    from apps.orgs.models import Membership

    required = MarketplaceSettings.for_tenant(tenant).mfa_required_roles
    if not required:
        return False
    return Membership.objects.filter(
        user=user, organization__tenant=tenant, is_active=True, role__key__in=required
    ).exists()
