"""Operator import of suppliers, customers and products from other systems (CSV or Excel)."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.audit.services import log
from apps.catalog import csv_import
from apps.core.validators import (
    normalize_iban,
    normalize_swiss_uid,
    validate_iban,
    validate_swiss_uid,
)
from apps.customers.models import Address
from apps.operator.models import SupplierTerms
from apps.orgs.models import Invitation, Membership, Organization
from apps.orgs.services import create_organization_without_owner, default_owner_role
from apps.suppliers.models import CANTONS

from .models import ImportBatch
from .reader import map_columns, norm

CANTON_CODES = {c for c, _ in CANTONS}

COMMON = {
    "name": [
        "firma",
        "firmenname",
        "betrieb",
        "betriebsname",
        "unternehmen",
        "company",
        "organisation",
        "kunde",
        "kundenname",
        "lieferant",
        "lieferantenname",
        "produzent",
        "hof",
        "anbieter",
    ],
    "email": ["e-mail", "emailadresse", "mail", "kontaktemail", "kontakt e-mail", "e_mail"],
    "phone": ["telefon", "tel", "telefonnummer", "phone", "natel", "mobile", "handy", "mobil"],
    "street": ["strasse", "adresse", "address", "street", "strasse und nr", "strasse nr", "strassenr", "anschrift"],
    "zip": ["plz", "postleitzahl", "zip", "zipcode", "postcode"],
    "city": ["ort", "stadt", "city", "ortschaft", "gemeinde"],
    "canton": ["kanton", "canton", "kt"],
    "vat": ["mwst", "mwst-nr", "mwstnr", "mwst nummer", "uid", "uid-nr", "vat", "vat number"],
}
SUPPLIER_ALIASES = {
    **COMMON,
    "legal_name": ["rechtlicher name", "firmenname rechtlich", "legal name"],
    "iban": ["iban", "konto", "bankkonto", "kontonummer"],
    "website": ["webseite", "homepage", "web", "url", "internet"],
    "description": ["beschreibung", "description", "info", "ueber uns", "text"],
    "commission": ["provision", "commission", "marge", "provision %"],
}
CUSTOMER_ALIASES = {
    **COMMON,
    "type": ["art", "typ", "kundenart", "kundentyp", "type"],
    "billing_email": ["rechnungsemail", "rechnung e-mail", "email rechnung", "billing email"],
    "ship_street": ["lieferstrasse", "lieferadresse", "liefer strasse"],
    "ship_zip": ["lieferplz", "liefer plz"],
    "ship_city": ["lieferort", "liefer ort"],
    "ship_canton": ["lieferkanton"],
    "ship_notes": ["lieferhinweis", "hinweis", "bemerkung lieferung", "lieferbemerkung"],
}
PRODUCT_ALIASES = {
    "lieferant": ["lieferant", "produzent", "anbieter", "hersteller", "supplier"],
    "artikel": ["artikelname", "artikelbezeichnung", "produkt", "produktname", "bezeichnung", "name", "product"],
    "variante": ["groesse", "gebinde", "packung", "verpackung", "inhalt", "menge pro einheit", "variant"],
    "einheit": ["unit", "verkaufseinheit", "mengeneinheit"],
    "kundenpreis": ["preis", "vk", "vkpreis", "verkaufspreis", "endpreis", "price", "preis chf"],
    "mwst": ["mwst satz", "mwst %", "steuersatz", "vat"],
    "mindestmenge": ["minmenge", "mindestbestellmenge", "min menge"],
    "kategorie": ["warengruppe", "category", "rubrik", "gruppe"],
    "temperatur": ["lagerung", "kuehlung", "temperature"],
    "haltbarkeit_tage": ["haltbarkeit", "haltbarkeit tage", "mhd tage"],
    "vorlaufzeit_tage": ["vorlaufzeit", "vorlauf", "lead time"],
    "herkunft": ["origin", "region"],
    "artikelnummer": ["artnr", "art nr", "artikel nr", "sku", "nummer", "ean"],
    "beschreibung": ["description", "text", "info"],
}


@dataclass
class ImportRow:
    line: int
    data: dict
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    action: str = "neu"

    @property
    def ok(self):
        return not self.errors


def _check_common(row, tenant, kind):
    d = row.data
    if not d.get("name"):
        row.errors.append("Name fehlt")
    if d.get("email"):
        try:
            validate_email(d["email"])
            d["email"] = d["email"].lower()
        except ValidationError:
            row.errors.append(f"E-Mail «{d['email']}» ungültig")
    else:
        row.notes.append("ohne E-Mail: keine Einladung möglich")
    if d.get("zip") and not (len(d["zip"]) == 4 and d["zip"].isdigit()):
        row.errors.append(f"PLZ «{d['zip']}» ungültig")
    if d.get("canton"):
        d["canton"] = d["canton"].upper()[:2]
        if d["canton"] not in CANTON_CODES:
            row.errors.append(f"Kanton «{d['canton']}» unbekannt")
    if d.get("vat"):
        try:
            validate_swiss_uid(d["vat"])
            d["vat"] = normalize_swiss_uid(d["vat"])
        except ValidationError:
            row.notes.append("MWST-Nr. ungültig – wird nicht übernommen")
            d["vat"] = ""
    if d.get("name") and Organization.objects.filter(tenant=tenant, kind=kind, name__iexact=d["name"]).exists():
        row.action = "existiert"
        row.notes.append("gibt es schon – wird übersprungen")


def parse_suppliers(rows, tenant):
    mapped, mapping, unknown = map_columns(rows, SUPPLIER_ALIASES)
    result, names = [], set()
    for i, data in enumerate(mapped, start=2):
        row = ImportRow(line=i, data=data)
        _check_common(row, tenant, "supplier")
        if data.get("iban"):
            try:
                validate_iban(data["iban"])
                data["iban"] = normalize_iban(data["iban"])
            except ValidationError:
                row.notes.append("IBAN ungültig – wird nicht übernommen")
                data["iban"] = ""
        if data.get("commission"):
            try:
                value = Decimal(data["commission"].replace("%", "").replace(",", ".").strip())
                if value < 1 and value > 0:
                    value *= 100  # 0.15 -> 15 %
                if not 0 <= value <= 100:
                    raise InvalidOperation
                data["commission"] = value.quantize(Decimal("0.01"))
            except InvalidOperation:
                row.errors.append(f"Provision «{data['commission']}» ungültig")
        _dedupe(row, names)
        result.append(row)
    return result, mapping, unknown


def parse_customers(rows, tenant):
    mapped, mapping, unknown = map_columns(rows, CUSTOMER_ALIASES)
    result, names = [], set()
    for i, data in enumerate(mapped, start=2):
        row = ImportRow(line=i, data=data)
        _check_common(row, tenant, "customer")
        data["type"] = (
            "private" if norm(data.get("type", "")) in {"privat", "private", "p", "privatkunde"} else "business"
        )
        if data.get("ship_zip") and not (len(data["ship_zip"]) == 4 and data["ship_zip"].isdigit()):
            row.errors.append(f"Liefer-PLZ «{data['ship_zip']}» ungültig")
        _dedupe(row, names)
        result.append(row)
    return result, mapping, unknown


def _dedupe(row, names):
    key = (row.data.get("name") or "").lower()
    if key and key in names:
        row.errors.append("Doppelt in der Datei")
    names.add(key)


@transaction.atomic
def apply_suppliers(rows, *, request, filename):
    batch = ImportBatch.objects.create(
        tenant=request.tenant, kind="suppliers", filename=filename, created_by=request.user
    )
    for row in rows:
        if not row.ok or row.action == "existiert":
            batch.skipped_count += 1
            continue
        d = row.data
        org = create_organization_without_owner(
            tenant=request.tenant, kind="supplier", name=d["name"][:160], status="active", request=request
        )
        p = org.supplier_profile
        p.legal_name = (d.get("legal_name") or d["name"])[:200]
        p.contact_email, p.phone = d.get("email", ""), d.get("phone", "")[:30]
        p.street, p.zip_code, p.city = d.get("street", "")[:200], d.get("zip", ""), d.get("city", "")[:100]
        p.canton = d.get("canton", "")
        p.vat_number, p.vat_registered = d.get("vat", ""), bool(d.get("vat"))
        p.iban, p.account_holder = d.get("iban", ""), (d["name"][:200] if d.get("iban") else "")
        p.website, p.description = d.get("website", "")[:200], d.get("description", "")
        p.save()
        if d.get("commission") not in (None, ""):
            SupplierTerms.objects.update_or_create(organization=org, defaults={"commission_percent": d["commission"]})
        batch.organizations.add(org)
        batch.created_count += 1
    batch.save()
    log(
        "import.done",
        request=request,
        organization=request.org,
        target=batch,
        changes={"art": "Lieferanten", "neu": batch.created_count, "übersprungen": batch.skipped_count},
    )
    return batch


@transaction.atomic
def apply_customers(rows, *, request, filename):
    batch = ImportBatch.objects.create(
        tenant=request.tenant, kind="customers", filename=filename, created_by=request.user
    )
    for row in rows:
        if not row.ok or row.action == "existiert":
            batch.skipped_count += 1
            continue
        d = row.data
        org = create_organization_without_owner(
            tenant=request.tenant,
            kind="customer",
            name=d["name"][:160],
            status="active",
            request=request,
            customer_type=d["type"],
        )
        p = org.customer_profile
        p.phone, p.vat_number = d.get("phone", "")[:30], d.get("vat", "")
        p.billing_email = d.get("billing_email") or d.get("email", "")
        p.billing_name = d["name"][:200]
        p.billing_street, p.billing_zip_code, p.billing_city = (
            d.get("street", "")[:200],
            d.get("zip", ""),
            d.get("city", "")[:100],
        )
        p.save()
        street = d.get("ship_street") or d.get("street")
        zip_code = d.get("ship_zip") or d.get("zip")
        city = d.get("ship_city") or d.get("city")
        if street and zip_code and city:
            Address.objects.create(
                organization=org,
                label="Lieferadresse",
                recipient=d["name"][:200],
                street=street[:200],
                zip_code=zip_code,
                city=city[:100],
                canton=(d.get("ship_canton") or d.get("canton") or "").upper()[:2],
                delivery_notes=d.get("ship_notes", "")[:300],
                is_default=True,
            )
        batch.organizations.add(org)
        batch.created_count += 1
    batch.save()
    log(
        "import.done",
        request=request,
        organization=request.org,
        target=batch,
        changes={"art": "Kunden", "neu": batch.created_count, "übersprungen": batch.skipped_count},
    )
    return batch


# --- products ------------------------------------------------------------------------------------


def parse_products(rows, tenant, supplier=None):
    """Rows may name their supplier in a «Lieferant» column; otherwise all go to `supplier`.
    Returns ({supplier: [catalog rows]}, errors_without_supplier, mapping, unknown)."""
    mapped, mapping, unknown = map_columns(rows, PRODUCT_ALIASES)
    suppliers = {o.name.lower(): o for o in Organization.objects.filter(tenant=tenant, kind="supplier")}
    groups, orphans = {}, []
    for i, data in enumerate(mapped, start=2):
        target = supplier
        if data.get("lieferant"):
            target = suppliers.get(data["lieferant"].lower())
        if target is None:
            orphans.append(
                ImportRow(
                    line=i,
                    data={"name": data.get("artikel", "")},
                    errors=[
                        f"Lieferant «{data.get('lieferant', '')}» unbekannt"
                        if data.get("lieferant")
                        else "Kein Lieferant gewählt"
                    ],
                )
            )
            continue
        groups.setdefault(target, []).append((i, data))
    parsed = {}
    for target, records in groups.items():
        rows_, error = csv_import.parse_rows(
            records, supplier=target, create_categories=True, default_variant="Standard"
        )
        if error:
            orphans.append(ImportRow(line=0, data={"name": target.name}, errors=[error]))
        parsed[target] = rows_
    return parsed, orphans, mapping, unknown


@transaction.atomic
def apply_products(parsed, *, request, filename):
    batch = ImportBatch.objects.create(
        tenant=request.tenant, kind="products", filename=filename, created_by=request.user
    )
    for target, rows in parsed.items():
        good = [r for r in rows if not r.errors]
        batch.skipped_count += len(rows) - len(good)
        if good:
            created, updated = csv_import.apply(good, supplier=target)
            batch.created_count += created
            batch.updated_count += updated
            batch.organizations.add(target)
    batch.save()
    log(
        "import.done",
        request=request,
        organization=request.org,
        target=batch,
        changes={
            "art": "Artikel",
            "neu": batch.created_count,
            "aktualisiert": batch.updated_count,
            "übersprungen": batch.skipped_count,
        },
    )
    return batch


# --- invitations ---------------------------------------------------------------------------------


def invite_owner(*, org, email, request):
    """Invite the first owner of an imported organization."""
    from apps.orgs import services as org_services
    from apps.orgs.views import _send_invitation

    invitation, token = org_services.invite(
        organization=org, email=email, role=default_owner_role(org.kind), request=request
    )
    _send_invitation(request, invitation, token)
    return invitation


def invite_batch(batch, request):
    sent = skipped = 0
    for org in batch.organizations.all():
        email = _contact_email(org)
        has_members = Membership.objects.filter(organization=org).exists()
        has_open = Invitation.objects.open().filter(organization=org).exists()
        if not email or has_members or has_open:
            skipped += 1
            continue
        invite_owner(org=org, email=email, request=request)
        sent += 1
    return sent, skipped


def _contact_email(org):
    if org.kind == "supplier":
        return org.supplier_profile.contact_email
    if org.kind == "customer":
        return org.customer_profile.billing_email
    return ""
