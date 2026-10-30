"""CSV import for suppliers: parse + validate everything first, write only when all rows are clean."""

import csv
import io
from dataclasses import dataclass, field

from django.db import transaction

from . import pricing
from .forms import parse_decimal
from .models import Category, Product, Temperature, Unit, Variant, VatRate

MAX_ROWS = 2000
COLUMNS = [
    "artikel",
    "variante",
    "einheit",
    "kundenpreis",
    "mwst",
    "mindestmenge",
    "kategorie",
    "temperatur",
    "haltbarkeit_tage",
    "vorlaufzeit_tage",
    "herkunft",
    "artikelnummer",
    "beschreibung",
]
REQUIRED = ["artikel", "variante", "kundenpreis", "kategorie"]
TEMPERATURES = {
    "ungekühlt": Temperature.AMBIENT,
    "ungekuehlt": Temperature.AMBIENT,
    "": Temperature.AMBIENT,
    "gekühlt": Temperature.CHILLED,
    "gekuehlt": Temperature.CHILLED,
    "tiefgekühlt": Temperature.FROZEN,
    "tiefgekuehlt": Temperature.FROZEN,
}
UNITS = {u.value.lower(): u.value for u in Unit}
VAT = {
    "2.6": VatRate.REDUCED,
    "2,6": VatRate.REDUCED,
    "8.1": VatRate.NORMAL,
    "8,1": VatRate.NORMAL,
    "0": VatRate.NONE,
    "": VatRate.REDUCED,
}

TEMPLATE = (
    ";".join(COLUMNS) + "\n"
    "Kartoffeln festkochend;2,5 kg;Kiste;9.50;2.6;1;Gemüse;ungekühlt;30;1;Liestal BL;KAR-25;Sorte Agria\n"
    "Bergkäse;250 g;Stk;7.80;2.6;2;Käse;gekühlt;60;2;Laufen BL;BK-250;12 Monate gereift\n"
)


@dataclass
class Row:
    line: int
    data: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    action: str = ""


def parse(text, *, supplier):
    """Return (rows, header_error). Each row carries its own errors."""
    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        return [], f"Spalten fehlen: {', '.join(missing)}. Bitte die Vorlage verwenden."
    reader.fieldnames = headers

    categories = {c.name.lower(): c for c in Category.objects.filter(tenant=supplier.tenant)}
    existing_skus = dict(Variant.objects.filter(product__supplier=supplier).exclude(sku="").values_list("sku", "pk"))
    rows, seen = [], set()
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            return rows, f"Maximal {MAX_ROWS} Zeilen pro Import."
        values = {k: (v or "").strip() for k, v in raw.items() if k}
        if not any(values.values()):
            continue
        row = Row(line=i)
        for col in REQUIRED:
            if not values.get(col):
                row.errors.append(f"{col} fehlt")
        try:
            price = parse_decimal(values.get("kundenpreis"))
            if price is not None:
                if price <= 0:
                    row.errors.append("Kundenpreis muss grösser als 0 sein")
                price = pricing.round_5_rappen(price)
            min_qty = parse_decimal(values.get("mindestmenge")) or 1
            shelf = parse_decimal(values.get("haltbarkeit_tage"))
            lead = parse_decimal(values.get("vorlaufzeit_tage"))
        except ValueError as exc:
            row.errors.append(str(exc))
            price = min_qty = shelf = lead = None
        unit = UNITS.get(values.get("einheit", "").lower() or "stk")
        if unit is None:
            row.errors.append(f"Einheit «{values.get('einheit')}» unbekannt ({', '.join(UNITS.values())})")
        temperature = TEMPERATURES.get(values.get("temperatur", "").lower())
        if temperature is None:
            row.errors.append("Temperatur: ungekühlt, gekühlt oder tiefgekühlt")
        vat = VAT.get(values.get("mwst", "").replace("%", "").strip())
        if vat is None:
            row.errors.append("MWST: 2.6, 8.1 oder 0")
        category = categories.get(values.get("kategorie", "").lower())
        if values.get("kategorie") and category is None:
            row.errors.append(f"Kategorie «{values.get('kategorie')}» gibt es nicht")
        key = (values.get("artikel", "").lower(), values.get("variante", "").lower())
        if key in seen:
            row.errors.append("Doppelte Zeile (gleicher Artikel und Variante)")
        seen.add(key)
        row.data = {
            "name": values.get("artikel", "")[:120],
            "variant": values.get("variante", "")[:60],
            "unit": unit,
            "price": price,
            "vat": vat,
            "min_qty": min_qty,
            "category": category,
            "temperature": temperature,
            "shelf_life_days": int(shelf) if shelf is not None else None,
            "lead_time_days": int(lead) if lead is not None else 1,
            "origin": values.get("herkunft", "")[:120],
            "sku": values.get("artikelnummer", "")[:40],
            "description": values.get("beschreibung", ""),
        }
        sku = row.data["sku"]
        exists = (sku and sku in existing_skus) or Variant.objects.filter(
            product__supplier=supplier, product__name__iexact=row.data["name"], name__iexact=row.data["variant"]
        ).exists()
        row.action = "aktualisieren" if exists else "neu"
        rows.append(row)
    if not rows:
        return [], "Die Datei enthält keine Zeilen."
    return rows, None


@transaction.atomic
def apply(rows, *, supplier):
    created = updated = 0
    for row in rows:
        d = row.data
        variant = None
        if d["sku"]:
            variant = Variant.objects.filter(product__supplier=supplier, sku=d["sku"]).select_related("product").first()
        product = (
            variant.product if variant else Product.objects.filter(supplier=supplier, name__iexact=d["name"]).first()
        )
        if product is None:
            product = Product(tenant=supplier.tenant, supplier=supplier, name=d["name"])
        product.category = d["category"]
        product.temperature = d["temperature"]
        product.lead_time_days = d["lead_time_days"]
        if d["shelf_life_days"] is not None:
            product.shelf_life_days = d["shelf_life_days"]
        if d["origin"]:
            product.origin = d["origin"]
        if d["description"]:
            product.description = d["description"]
        product.save()
        if variant is None:
            variant = Variant.objects.filter(product=product, name__iexact=d["variant"]).first()
        if variant is None:
            variant = Variant(product=product)
            created += 1
        else:
            updated += 1
        variant.name, variant.unit, variant.customer_price = d["variant"], d["unit"], d["price"]
        variant.vat_rate, variant.min_qty, variant.sku = d["vat"], d["min_qty"], d["sku"]
        variant.save()
    return created, updated
