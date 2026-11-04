from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog import pricing
from apps.catalog.defaults import seed_catalog_defaults
from apps.catalog.models import Category, Product, Variant

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog(tenant):
    seed_catalog_defaults(tenant)
    return tenant


def make_product(supplier, name="Kartoffeln", price="9.50", **extra):
    product = Product.objects.create(
        tenant=supplier.tenant,
        supplier=supplier,
        name=name,
        category=Category.objects.get(tenant=supplier.tenant, name="Kartoffeln"),
        **extra,
    )
    Variant.objects.create(product=product, name="2,5 kg", customer_price=Decimal(price))
    return product


def product_post(name="Rüebli", basis="customer", customer="3.80", supplier="", **extra):
    data = {
        "name": name,
        "category": Category.objects.get(name="Gemüse").pk,
        "temperature": "ambient",
        "lead_time_days": "1",
        "is_active": "on",
        "v-TOTAL_FORMS": "1",
        "v-INITIAL_FORMS": "0",
        "v-MIN_NUM_FORMS": "1",
        "v-MAX_NUM_FORMS": "1000",
        "v-0-name": "1 kg",
        "v-0-unit": "kg",
        "v-0-customer_price": customer,
        "v-0-supplier_price": supplier,
        "v-0-price_basis": basis,
        "v-0-vat_rate": "2.6",
        "v-0-min_qty": "1",
        "v-0-qty_step": "1",
        "v-0-is_active": "on",
    }
    data.update(extra)
    return data


# --- Pricing ---------------------------------------------------------------------------------------


def test_pricing_both_directions():
    assert pricing.supplier_net(Decimal("10.00"), Decimal("15")) == Decimal("8.50")
    assert pricing.customer_price_from_supplier(Decimal("8.50"), Decimal("15")) == Decimal("10.00")
    assert pricing.round_5_rappen(Decimal("3.33")) == Decimal("3.35")
    assert pricing.round_5_rappen(Decimal("3.32")) == Decimal("3.30")


def test_supplier_enters_own_price_and_gets_customer_price(login, supplier_a, catalog):
    login(supplier_a.owner).post(reverse("catalog:new"), product_post(basis="supplier", customer="", supplier="8.50"))
    variant = Variant.objects.get(product__name="Rüebli")
    assert variant.customer_price == Decimal("10.00")  # default commission 15 %


def test_customer_price_is_rounded(login, supplier_a, catalog):
    login(supplier_a.owner).post(reverse("catalog:new"), product_post(customer="3.33"))
    assert Variant.objects.get(product__name="Rüebli").customer_price == Decimal("3.35")


def test_supplier_specific_commission_is_used(login, supplier_a, catalog):
    supplier_a.terms.commission_percent = Decimal("20")
    supplier_a.terms.save()
    login(supplier_a.owner).post(reverse("catalog:new"), product_post(basis="supplier", customer="", supplier="8.00"))
    assert Variant.objects.get(product__name="Rüebli").customer_price == Decimal("10.00")


def test_price_change_is_logged(login, supplier_a, catalog):
    client = login(supplier_a.owner)
    client.post(reverse("catalog:new"), product_post())
    product = Product.objects.get(name="Rüebli")
    variant = product.variants.get()
    data = product_post(customer="4.20")
    data.update({"v-INITIAL_FORMS": "1", "v-0-id": variant.pk, "v-0-product": product.pk})
    client.post(reverse("catalog:edit", args=[product.pk]), data)
    event = AuditEvent.objects.filter(action="catalog.updated", organization=supplier_a).latest("created_at")
    assert event.changes == {"1 kg": ["3.80", "4.20"]}


# --- Access ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["clerk", "readonly"])
def test_clerk_and_readonly_cannot_create_products(login, supplier_a, catalog, role):
    login(getattr(supplier_a, role)).post(reverse("catalog:new"), product_post())
    assert not Product.objects.exists()


def test_clerk_cannot_change_price(login, supplier_a, catalog):
    product = make_product(supplier_a)
    variant = product.variants.get()
    data = product_post(name="Kartoffeln", customer="1.00")
    data.update({"v-INITIAL_FORMS": "1", "v-0-id": variant.pk, "v-0-product": product.pk})
    login(supplier_a.clerk).post(reverse("catalog:edit", args=[product.pk]), data)
    variant.refresh_from_db()
    assert variant.customer_price == Decimal("9.50")


def test_supplier_cannot_touch_other_suppliers_products(login, supplier_a, supplier_b, catalog):
    product = make_product(supplier_b)
    client = login(supplier_a.owner)
    assert client.get(reverse("catalog:edit", args=[product.pk])).status_code == 404
    assert client.post(reverse("catalog:toggle", args=[product.pk])).status_code == 404
    assert client.post(reverse("catalog:delete", args=[product.pk])).status_code == 404
    assert b"Kartoffeln" not in client.get(reverse("catalog:list")).content
    assert Product.objects.filter(pk=product.pk, is_active=True).exists()


def test_customer_cannot_open_catalog_admin(login, customer, catalog):
    assert login(customer.owner).get(reverse("catalog:list")).status_code == 403


@pytest.mark.parametrize("who", ["staff", "supplier"])
def test_only_operator_admin_manages_categories(login, operator, supplier_a, catalog, who):
    user = operator.staff if who == "staff" else supplier_a.owner
    client = login(user)
    assert client.get(reverse("catalog_admin:taxonomy")).status_code == 403
    assert client.post(reverse("catalog_admin:label_add"), {"name": "Hack"}).status_code == 403


def test_category_with_products_cannot_be_deleted(login, operator, supplier_a, catalog):
    product = make_product(supplier_a)
    login(operator.admin).post(reverse("catalog_admin:category_delete", args=[product.category_id]))
    assert Category.objects.filter(pk=product.category_id).exists()


# --- Shop visibility & search ----------------------------------------------------------------------


def test_shop_requires_login(client, catalog):
    response = client.get(reverse("shop:index"))
    assert response.status_code == 302 and "/konto/login/" in response["Location"]


def test_shop_shows_only_visible_products(login, customer, supplier_a, supplier_b, catalog):
    visible = make_product(supplier_a, name="Sichtbar")
    hidden = make_product(supplier_a, name="Ausgeblendet", is_active=False)
    supplier_b.status = "pending"
    supplier_b.save()
    pending = make_product(supplier_b, name="Wartend")
    no_variant = Product.objects.create(tenant=supplier_a.tenant, supplier=supplier_a, name="OhneVariante")
    client = login(customer.owner)
    page = client.get(reverse("shop:index")).content.decode()
    assert "Sichtbar" in page
    for name in ("Ausgeblendet", "Wartend", "OhneVariante"):
        assert name not in page
    for product in (hidden, pending, no_variant):
        assert client.get(reverse("shop:product", args=[product.pk])).status_code == 404
    assert client.get(reverse("shop:product", args=[visible.pk])).status_code == 200
    assert client.get(reverse("shop:supplier", args=[supplier_b.pk])).status_code == 404


def test_search_tolerates_typos_and_word_starts(login, customer, supplier_a, catalog):
    make_product(supplier_a, name="Kartoffeln festkochend")
    cheese = make_product(supplier_a, name="Bergkäse")
    cheese.category = Category.objects.get(name="Käse")
    cheese.save()
    client = login(customer.owner)
    for q in ("kartofel", "Kartoff", "kartoffel"):
        page = client.get(
            reverse("shop:index"), {"q": q}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="results"
        ).content.decode()
        assert "Kartoffeln festkochend" in page, q
        assert "Bergkäse" not in page, q


def test_search_partial_for_htmx(login, customer, supplier_a, catalog):
    make_product(supplier_a, name="Kartoffeln")
    response = login(customer.owner).get(
        reverse("shop:index"), {"q": "kart"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="results"
    )
    body = response.content.decode()
    assert "Kartoffeln" in body and "<html" not in body


def test_filter_by_category_includes_children(login, customer, supplier_a, catalog):
    make_product(supplier_a, name="Agria")  # category Kartoffeln (child of Gemüse)
    gemuese = Category.objects.get(name="Gemüse", parent__isnull=True)
    page = login(customer.owner).get(reverse("shop:index"), {"kategorie": gemuese.pk}).content.decode()
    assert "Agria" in page


# --- CSV import ------------------------------------------------------------------------------------

CSV_OK = (
    "artikel;variante;einheit;kundenpreis;mwst;mindestmenge;kategorie;temperatur;artikelnummer\n"
    "Bergkäse;250 g;Stk;7,80;2.6;2;Käse;gekühlt;BK-250\n"
    "Bergkäse;1 kg;kg;28.50;2.6;1;Käse;gekühlt;BK-1000\n"
)
CSV_BAD = (
    "artikel;variante;kundenpreis;kategorie;temperatur\n"
    "Bergkäse;250 g;abc;Käse;lauwarm\n"
    "Rahm;;3.00;Gibtsnicht;gekühlt\n"
)


def _upload(client, text):
    return client.post(reverse("catalog:csv"), {"file": SimpleUploadedFile("a.csv", text.encode("utf-8"))})


def test_csv_import_preview_then_confirm(login, supplier_a, catalog):
    client = login(supplier_a.owner)
    response = _upload(client, CSV_OK)
    assert "Jetzt 2 Zeilen importieren" in response.content.decode()
    assert not Product.objects.exists()  # nothing written before confirmation
    client.post(reverse("catalog:csv_confirm"))
    product = Product.objects.get(name="Bergkäse", supplier=supplier_a)
    assert product.temperature == "chilled"
    assert set(product.variants.values_list("sku", "customer_price")) == {
        ("BK-250", Decimal("7.80")),
        ("BK-1000", Decimal("28.50")),
    }
    # second import updates by SKU instead of duplicating
    _upload(client, CSV_OK.replace("7,80", "8.20"))
    client.post(reverse("catalog:csv_confirm"))
    assert Variant.objects.filter(product__supplier=supplier_a).count() == 2
    assert Variant.objects.get(sku="BK-250").customer_price == Decimal("8.20")


def test_csv_import_with_errors_writes_nothing(login, supplier_a, catalog):
    client = login(supplier_a.owner)
    page = _upload(client, CSV_BAD).content.decode()
    assert "keine Zahl" in page and "Temperatur" in page and "Gibtsnicht" in page and "variante fehlt" in page
    client.post(reverse("catalog:csv_confirm"))
    assert not Product.objects.exists()


def test_csv_import_needs_price_permission(login, supplier_a, catalog):
    assert login(supplier_a.clerk).get(reverse("catalog:csv")).status_code == 403


def test_csv_export_only_own_products(login, supplier_a, supplier_b, catalog):
    make_product(supplier_a, name="EigenesProdukt")
    make_product(supplier_b, name="FremdesProdukt")
    body = login(supplier_a.owner).get(reverse("catalog:csv_export")).content.decode("utf-8-sig")
    assert "EigenesProdukt" in body and "FremdesProdukt" not in body


def test_image_upload_is_resized_and_thumbnailed(login, supplier_a, catalog, settings, tmp_path):
    from io import BytesIO

    from PIL import Image

    settings.MEDIA_ROOT = tmp_path
    buf = BytesIO()
    Image.new("RGB", (2400, 1800), "green").save(buf, "PNG")
    data = product_post()
    data["image"] = SimpleUploadedFile("foto.png", buf.getvalue(), content_type="image/png")
    login(supplier_a.owner).post(reverse("catalog:new"), data)
    product = Product.objects.get(name="Rüebli")
    assert product.image.name.endswith(".webp") and product.thumbnail.name.endswith(".webp")
    with Image.open(product.image.path) as big, Image.open(product.thumbnail.path) as small:
        assert max(big.size) == 1200 and max(small.size) == 400


def test_non_image_upload_is_rejected(login, supplier_a, catalog):
    data = product_post()
    data["image"] = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
    login(supplier_a.owner).post(reverse("catalog:new"), data)
    assert not Product.objects.exists()
