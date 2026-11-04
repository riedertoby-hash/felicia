from decimal import Decimal
from io import BytesIO

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.catalog.defaults import seed_catalog_defaults
from apps.catalog.models import Category, Product
from apps.imports.models import ImportBatch
from apps.orgs.models import Invitation, Organization

pytestmark = pytest.mark.django_db

SUPPLIERS_CSV = (
    "Firma;E-Mail;Telefon;Strasse;PLZ;Ort;Kanton;MWST-Nr;IBAN;Provision;Unbekannt\n"
    "Hof Rheinblick;info@rheinblick.ch;061 111 11 11;Rheinweg 1;4058;Basel;BS;;CH93 0076 2011 6238 5295 7;12%;x\n"
    "Mühle Ergolz;;;Mühleweg 2;4414;Füllinsdorf;bl;CHE-000.000.000;falsch;0.1;\n"
    "Kaputt;keine-mail;;;44;;ZZ;;;;\n"
)
CUSTOMERS_CSV = (
    "Kundenname,Art,E-Mail,Adresse,PLZ,Ort,Kanton,Lieferhinweis\n"
    "Restaurant Krone,Betrieb,chef@krone.ch,Marktplatz 1,4001,Basel,BS,Hintereingang\n"
    "Anna Muster,privat,anna@muster.ch,Weg 3,4410,Liestal,BL,\n"
)


def upload(client, kind, content, name="daten.csv", supplier=None):
    data = {"kind": kind, "file": SimpleUploadedFile(name, content)}
    if supplier:
        data["supplier"] = supplier.pk
    return client.post(reverse("imports:upload"), data)


def test_supplier_import_with_foreign_headers(login, operator, tenant):
    client = login(operator.admin)
    page = upload(client, "suppliers", SUPPLIERS_CSV.encode("cp1252")).content.decode()
    assert "Firma → name" in page and "Unbekannt" in page  # mapping and ignored column shown
    assert "PLZ «44» ungültig" in page and "Kanton «ZZ» unbekannt" in page
    assert not Organization.objects.filter(kind="supplier").exists()  # nothing before confirmation
    client.post(reverse("imports:confirm"))
    hof = Organization.objects.get(name="Hof Rheinblick")
    assert hof.status == "active" and hof.supplier_profile.iban == "CH9300762011623852957"
    assert hof.terms.commission_percent == Decimal("12.00")
    muehle = Organization.objects.get(name="Mühle Ergolz")
    assert muehle.supplier_profile.canton == "BL" and muehle.supplier_profile.iban == ""
    assert muehle.terms.commission_percent == Decimal("10.00")  # 0.1 -> 10 %
    assert not Organization.objects.filter(name="Kaputt").exists()
    batch = ImportBatch.objects.get()
    assert (batch.created_count, batch.skipped_count) == (2, 1)
    # running the same file again skips existing suppliers
    upload(client, "suppliers", SUPPLIERS_CSV.encode())
    client.post(reverse("imports:confirm"))
    assert Organization.objects.filter(name="Hof Rheinblick").count() == 1


def test_customer_import_from_excel_and_invitations(login, operator, tenant, client):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for line in CUSTOMERS_CSV.splitlines():
        ws.append(line.split(","))
    buf = BytesIO()
    wb.save(buf)
    admin = login(operator.admin)
    upload(admin, "customers", buf.getvalue(), name="kunden.xlsx")
    admin.post(reverse("imports:confirm"))
    krone = Organization.objects.get(name="Restaurant Krone")
    assert krone.customer_profile.customer_type == "business"
    address = krone.addresses.get()
    assert (address.zip_code, address.canton, address.delivery_notes) == ("4001", "BS", "Hintereingang")
    assert Organization.objects.get(name="Anna Muster").customer_profile.customer_type == "private"
    assert not mail.outbox  # invitations only when asked
    batch = ImportBatch.objects.get()
    admin.post(reverse("imports:batch_invite", args=[batch.pk]))
    assert {m.to[0] for m in mail.outbox} == {"chef@krone.ch", "anna@muster.ch"}
    admin.post(reverse("imports:batch_invite", args=[batch.pk]))  # no duplicates
    assert len(mail.outbox) == 2
    # the invited owner can sign up and becomes owner of the imported business
    token = next(m for m in mail.outbox if m.to == ["chef@krone.ch"]).body.split("/team/einladung/")[1].split("/")[0]
    client.logout()
    client.post(
        reverse("orgs:accept", args=[token]),
        {
            "first_name": "Chef",
            "last_name": "Krone",
            "password1": "Zwiebel-Rostbraten-2026!",
            "password2": "Zwiebel-Rostbraten-2026!",
            "accept_terms": "on",
        },
    )
    membership = krone.memberships.get()
    assert membership.user.email == "chef@krone.ch" and membership.role.key == "customer_owner"


def test_product_import_routes_by_supplier_column(login, operator, supplier_a, supplier_b, tenant):
    seed_catalog_defaults(tenant)
    csv = (
        "Lieferant;Artikelname;Preis;Warengruppe;Artnr;Lagerung\n"
        "Hof A;Kartoffeln;9,50;Kartoffeln;A-1;\n"
        "Hof B;Ziegenkäse;8.20;Spezialitäten;B-1;gekühlt\n"
        "Unbekannt AG;Brot;5.00;Brot & Backwaren;X-1;\n"
    ).encode()
    client = login(operator.admin)
    page = upload(client, "products", csv).content.decode()
    assert "Lieferant «Unbekannt AG» unbekannt" in page
    client.post(reverse("imports:confirm"))
    potato = Product.objects.get(name="Kartoffeln")
    assert potato.supplier == supplier_a and potato.variants.get().name == "Standard"
    cheese = Product.objects.get(name="Ziegenkäse")
    assert cheese.supplier == supplier_b and cheese.temperature == "chilled"
    assert cheese.category == Category.objects.get(name="Spezialitäten")  # created on the fly
    assert not Product.objects.filter(name="Brot").exists()


def test_product_import_for_chosen_supplier(login, operator, supplier_a, tenant):
    seed_catalog_defaults(tenant)
    client = login(operator.admin)
    upload(client, "products", b"Produkt;VK-Preis\nHonig;12.00\n", supplier=supplier_a)
    client.post(reverse("imports:confirm"))
    honey = Product.objects.get(name="Honig")
    assert honey.supplier == supplier_a and honey.category.name == "Diverses"


def test_bad_files_are_rejected(login, operator):
    client = login(operator.admin)
    page = upload(client, "suppliers", b"", name="leer.csv").content.decode()
    assert "leer" in page
    page = upload(client, "suppliers", b"Firma;Ort\n", name="nur-kopf.csv").content.decode()
    assert "keine Datenzeilen" in page
    page = upload(client, "suppliers", b"not excel", name="x.xlsx").content.decode()
    assert "Excel-Datei konnte nicht gelesen werden" in page


@pytest.mark.parametrize("who", ["staff", "supplier", "customer"])
def test_only_operator_admin_can_import(login, operator, supplier_a, customer, who):
    user = {"staff": operator.staff, "supplier": supplier_a.owner, "customer": customer.owner}[who]
    client = login(user)
    assert client.get(reverse("imports:upload")).status_code == 403
    assert client.post(reverse("imports:invite_org", args=[supplier_a.pk]), {"email": "x@y.ch"}).status_code == 403
    assert not Invitation.objects.exists()
