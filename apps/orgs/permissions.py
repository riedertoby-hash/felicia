"""Permission catalogue. Roles (in the database) bundle these keys, so new roles need no code change."""

PERMISSIONS = {
    # shared (any organization)
    "org.view": "Profil ansehen",
    "org.edit": "Profil bearbeiten",
    "team.manage": "Benutzer einladen und Rollen vergeben",
    "finance.view": "Umsätze, Rechnungen und Auszahlungen einsehen",
    # supplier
    "org.bank": "Bankverbindung verwalten",
    "catalog.view": "Artikel ansehen",
    "catalog.edit": "Artikel bearbeiten",
    "prices.edit": "Preise bearbeiten",
    "delivery.edit": "Lieferzonen und Konditionen bearbeiten",
    "orders.view": "Bestellungen ansehen",
    "orders.manage": "Bestellungen bearbeiten, Lieferscheine drucken",
    # customer
    "shop.order": "Bestellen",
    "customer.addresses": "Adressen verwalten",
    # operator
    "platform.suppliers.view": "Lieferanten einsehen",
    "platform.suppliers.manage": "Lieferanten freischalten und sperren",
    "platform.customers.view": "Kunden einsehen",
    "platform.terms": "Provisionen und Gebühren festlegen",
    "platform.settings": "Marktplatz-Einstellungen und Sicherheitsregeln",
    "platform.audit": "Protokoll einsehen",
}

_SUPPLIER_ALL = [
    "org.view",
    "org.edit",
    "org.bank",
    "team.manage",
    "finance.view",
    "catalog.view",
    "catalog.edit",
    "prices.edit",
    "delivery.edit",
    "orders.view",
    "orders.manage",
]

# key, kind, name, description, permissions, is_owner, sort
DEFAULT_ROLES = [
    (
        "operator_admin",
        "operator",
        "Super-Admin",
        "Voller Zugriff auf den Marktplatz",
        [
            "org.view",
            "org.edit",
            "team.manage",
            "finance.view",
            "platform.suppliers.view",
            "platform.suppliers.manage",
            "platform.customers.view",
            "platform.terms",
            "platform.settings",
            "platform.audit",
        ],
        True,
        10,
    ),
    (
        "operator_staff",
        "operator",
        "Betreiber-Mitarbeiter",
        "Lieferanten und Kunden einsehen, Support",
        ["org.view", "platform.suppliers.view", "platform.customers.view"],
        False,
        20,
    ),
    ("supplier_owner", "supplier", "Inhaber", "Alles, inkl. Benutzer und Bankverbindung", _SUPPLIER_ALL, True, 10),
    (
        "supplier_admin",
        "supplier",
        "Admin",
        "Artikel, Preise, Lieferzonen, Bestellungen",
        [p for p in _SUPPLIER_ALL if p not in ("org.bank", "team.manage")],
        False,
        20,
    ),
    (
        "supplier_clerk",
        "supplier",
        "Sachbearbeiter",
        "Bestellungen bearbeiten und drucken",
        ["org.view", "catalog.view", "orders.view", "orders.manage"],
        False,
        30,
    ),
    (
        "supplier_readonly",
        "supplier",
        "Nur Lesen",
        "Z.B. Buchhaltung: Umsätze und Rechnungen einsehen",
        ["org.view", "catalog.view", "orders.view", "finance.view"],
        False,
        40,
    ),
    (
        "customer_owner",
        "customer",
        "Inhaber",
        "Bestellen, Adressen, Benutzer verwalten",
        ["org.view", "org.edit", "team.manage", "finance.view", "shop.order", "customer.addresses"],
        True,
        10,
    ),
    (
        "customer_buyer",
        "customer",
        "Besteller",
        "Bestellen und eigene Bestellungen sehen",
        ["org.view", "shop.order"],
        False,
        20,
    ),
]

DEFAULT_MFA_REQUIRED_ROLES = ["operator_admin", "operator_staff", "supplier_owner", "supplier_admin"]
