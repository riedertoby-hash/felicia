from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.api.models import ApiKey
from apps.billing import services as billing
from apps.catalog.models import Variant
from apps.orders.models import Order
from tests.test_billing import delivered  # noqa: F401
from tests.test_orders import address  # noqa: F401

pytestmark = pytest.mark.django_db


def period_params(day):
    return {"zeitraum": "frei", "von": day.replace(day=1).isoformat(), "bis": day.isoformat()}


# --- reports -------------------------------------------------------------------------------------


def test_supplier_dashboard_and_exports(login, supplier_a, customer, delivered):  # noqa: F811
    billing.create_sale_invoice(supplier=supplier_a, customer=customer, orders=delivered)
    client = login(supplier_a.owner)
    day = delivered[0].delivery_date
    page = client.get(reverse("reports:dashboard"), period_params(day)).content.decode()
    assert "123" in page and "Restaurant Linde" in page and "Kartoffeln" in page
    journal = client.get(reverse("reports:export", args=["journal"]), {"zeitraum": "jahr"}).content.decode("utf-8-sig")
    lines = journal.strip().splitlines()
    assert lines[0].startswith("Datum;Beleg;Soll;Haben;Betrag")
    assert ";1100;3200;139.00;2.6;3.52;" in journal
    invoices = client.get(reverse("reports:export", args=["rechnungen"]), {"zeitraum": "jahr"})
    assert "Restaurant Linde" in invoices.content.decode("utf-8-sig")
    sales = client.get(reverse("reports:export", args=["umsatz"]), period_params(day)).content.decode("utf-8-sig")
    assert sales.count("Kartoffeln") == 2


def test_reports_only_own_data(login, supplier_a, supplier_b, delivered):  # noqa: F811
    client = login(supplier_b.owner)
    page = client.get(reverse("reports:dashboard"), {"zeitraum": "jahr"}).content.decode()
    assert "Restaurant Linde" not in page
    assert "Kartoffeln" not in client.get(
        reverse("reports:export", args=["umsatz"]), {"zeitraum": "jahr"}
    ).content.decode("utf-8-sig")


@pytest.mark.parametrize("who", ["clerk", "customer", "staff"])
def test_reports_permissions(login, supplier_a, customer, operator, who):
    user = {"clerk": supplier_a.clerk, "customer": customer.owner, "staff": operator.staff}[who]
    assert login(user).get(reverse("reports:dashboard")).status_code == 403


def test_operator_sees_all_suppliers(login, operator, supplier_a, delivered):  # noqa: F811
    page = login(operator.admin).get(reverse("reports:dashboard"), {"zeitraum": "jahr"}).content.decode()
    assert "Pro Lieferant" in page and "Hof A" in page


# --- API -----------------------------------------------------------------------------------------


def key_for(org, *scopes):
    _, raw = ApiKey.issue(organization=org, name="ERP", scopes=list(scopes), user=None)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def test_api_orders_and_status(client, supplier_a, delivered, django_capture_on_commit_callbacks):  # noqa: F811
    Order.objects.update(status="new")
    auth = key_for(supplier_a, "orders.read", "orders.write")
    data = client.get("/api/v1/orders", **auth).json()
    assert len(data["results"]) == 2 and data["results"][0]["lines"][0]["product"] == "Kartoffeln"
    number = data["results"][0]["number"]
    response = client.post(
        f"/api/v1/orders/{number}/status", data='{"status": "confirmed"}', content_type="application/json", **auth
    )
    assert response.status_code == 200 and response.json()["status"] == "confirmed"
    bad = client.post(
        f"/api/v1/orders/{number}/status", data='{"status": "new"}', content_type="application/json", **auth
    )
    assert bad.status_code == 400


def test_api_auth_and_scopes(client, supplier_a, supplier_b, delivered):  # noqa: F811
    assert client.get("/api/v1/orders").status_code == 401
    assert client.get("/api/v1/orders", HTTP_AUTHORIZATION="Bearer fel_wrong").status_code == 401
    read_only = key_for(supplier_a, "catalog.read")
    assert client.get("/api/v1/orders", **read_only).status_code == 403
    # another supplier's key sees none of A's orders (view filter and database row security)
    other = key_for(supplier_b, "orders.read")
    assert client.get("/api/v1/orders", **other).json()["results"] == []
    number = Order.objects.first().number
    assert client.get(f"/api/v1/orders/{number}", **other).status_code == 404
    # revoked keys stop working immediately
    key = ApiKey.objects.filter(organization=supplier_a).first()
    key.revoked_at = timezone.now()
    key.save()
    assert client.get("/api/v1/products", **read_only).status_code == 401


def test_api_stock_and_price_update(client, supplier_a, delivered):  # noqa: F811
    variant = Variant.objects.get()
    variant.sku = "KAR-1"
    variant.save()
    stock_only = key_for(supplier_a, "stock.write")
    r = client.patch("/api/v1/variants/KAR-1", data='{"stock": 42}', content_type="application/json", **stock_only)
    assert r.status_code == 200 and r.json()["stock"] == "42"
    r = client.patch(
        "/api/v1/variants/KAR-1", data='{"customer_price": "1"}', content_type="application/json", **stock_only
    )
    assert r.status_code == 403
    both = key_for(supplier_a, "stock.write", "prices.write")
    r = client.patch(
        "/api/v1/variants/KAR-1", data='{"customer_price": "11.33"}', content_type="application/json", **both
    )
    assert r.json()["customer_price"] == "11.35"
    variant.refresh_from_db()
    assert (variant.stock, variant.customer_price) == (Decimal("42"), Decimal("11.35"))


def test_key_ui_limits_scopes_and_shows_key_once(login, supplier_a):
    client = login(supplier_a.admin)  # admin has no bank/team rights but all catalog/order rights
    page = client.post(reverse("api:keys"), {"name": "ERP", "scopes": ["orders.read", "prices.write"]}).content
    key = ApiKey.objects.get()
    assert key.scopes == ["orders.read", "prices.write"]
    import re

    raw = re.search(rb'<code class="codes">(fel_[^<]+)</code>', page).group(1)
    assert ApiKey.hash(raw.decode()) == key.key_hash and key.key_hash.encode() not in page
    assert raw not in client.get(reverse("api:keys")).content  # full key never shown again
    assert login(supplier_a.clerk).get(reverse("api:keys")).status_code == 403


def test_rate_limit(client, supplier_a, settings):
    from apps.api import views

    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    auth = key_for(supplier_a, "catalog.read")
    old = views.RATE_LIMIT
    views.RATE_LIMIT = 3
    try:
        codes = [client.get("/api/v1/products", **auth).status_code for _ in range(5)]
    finally:
        views.RATE_LIMIT = old
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
