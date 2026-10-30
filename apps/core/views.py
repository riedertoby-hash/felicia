from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache


def home(request):
    if not request.user.is_authenticated:
        return render(request, "core/landing.html")
    org = getattr(request, "org", None)
    if org is None:
        return render(request, "core/no_org.html")
    return redirect(org.dashboard_url)


@never_cache
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "db": "down"}, status=503)
    return JsonResponse({"status": "ok"})


SETTINGS_PREFIXES = (
    "/einstellungen/",
    "/team/",
    "/konto/",
    "/lieferant/profil",
    "/lieferant/lieferung",
    "/lieferant/bank",
    "/lieferant/benachrichtigungen",
    "/lieferant/rechnungen/einstellungen",
    "/kunde/profil",
    "/kunde/adressen",
    "/betreiber/einstellungen",
    "/betreiber/katalog",
    "/betreiber/rechnungsdaten",
)


def settings_active(request):
    """Context processor: highlight «Einstellungen» in the navigation on all setup pages."""
    path = request.path
    return {"settings_active": path == "/kunde/" or path.startswith(SETTINGS_PREFIXES)}


def settings_hub(request):
    """One page that collects everything that is set up once and rarely touched."""
    from django.contrib.auth.views import redirect_to_login

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    org = getattr(request, "org", None)
    perms = set(request.membership.role.permissions) if getattr(request, "membership", None) else set()
    items = []

    def add(perm, title, text, url_name):
        if perm is None or perm in perms:
            items.append({"title": title, "text": text, "url": reverse(url_name)})

    if org is not None and org.kind == "supplier":
        add("org.view", "Profil", "Auftritt im Shop, Adresse, MWST, Abholzeiten", "suppliers:profile")
        add("org.view", "Lieferung & Abholung", "Lieferarten, Zonen, Mindestbestellwert, Gebühren", "delivery:overview")
        add("org.edit", "Benachrichtigungen", "Wie Sie von neuen Bestellungen erfahren", "suppliers:notifications")
        add(
            "finance.manage",
            "Rechnungsstellung",
            "Pro Bestellung, monatlich, quartalsweise oder manuell",
            "billing:supplier_settings",
        )
        add("org.bank", "Bankverbindung", "IBAN für den QR-Zahlteil Ihrer Rechnungen", "suppliers:bank")
    elif org is not None and org.kind == "customer":
        add("org.edit", "Profil & Rechnungsadresse", "Name, Rechnungsadresse, Kontakt", "customers:profile")
        add("customer.addresses", "Lieferadressen", "Wohin geliefert wird", "customers:addresses")
    elif org is not None and org.kind == "operator":
        add(
            "platform.settings", "Marktplatz", "Provision, Grundgebühr, Freischaltung, 2FA-Pflicht", "operator:settings"
        )
        add("platform.settings", "Kategorien & Labels", "Struktur des Shops", "catalog_admin:taxonomy")
        add(
            "platform.settings",
            "Rechnungsdaten",
            "Absender und IBAN für Provisionsrechnungen",
            "billing:operator_issuer",
        )
    add("team.manage", "Team", "Benutzer einladen und Rollen vergeben", "orgs:team")
    add(None, "Konto & Sicherheit", "Passwort, Zwei-Faktor-Anmeldung, Geräte", "account_security")
    return render(request, "core/settings_hub.html", {"items": items})
