from decimal import Decimal
from io import BytesIO

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Value
from django.utils import timezone
from PIL import Image

from apps.core.models import TenantModel


class Temperature(models.TextChoices):
    AMBIENT = "ambient", "Ungekühlt"
    CHILLED = "chilled", "Gekühlt (2–5 °C)"
    FROZEN = "frozen", "Tiefgekühlt (−18 °C)"


class Unit(models.TextChoices):
    PIECE = "Stk", "Stück"
    KG = "kg", "Kilogramm"
    G = "g", "Gramm"
    L = "l", "Liter"
    DL = "dl", "Deziliter"
    BUNCH = "Bund", "Bund"
    CRATE = "Kiste", "Kiste"
    JAR = "Glas", "Glas"
    BOTTLE = "Flasche", "Flasche"
    PACK = "Packung", "Packung"
    TRAY = "Schale", "Schale"


class VatRate(models.TextChoices):
    REDUCED = "2.6", "2,6 % (Lebensmittel)"
    NORMAL = "8.1", "8,1 % (Normalsatz)"
    NONE = "0", "keine MWST"


# The 14 allergens that must be declared in Switzerland (LIV, Anhang 6).
ALLERGENS = [
    ("gluten", "Gluten"),
    ("crustaceans", "Krebstiere"),
    ("eggs", "Eier"),
    ("fish", "Fisch"),
    ("peanuts", "Erdnüsse"),
    ("soy", "Soja"),
    ("milk", "Milch/Laktose"),
    ("nuts", "Schalenfrüchte (Nüsse)"),
    ("celery", "Sellerie"),
    ("mustard", "Senf"),
    ("sesame", "Sesam"),
    ("sulphites", "Sulfite"),
    ("lupin", "Lupinen"),
    ("molluscs", "Weichtiere"),
]
ALLERGEN_LABELS = dict(ALLERGENS)

MONTHS = [
    (i, n)
    for i, n in enumerate(["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"], start=1)
]


class Category(TenantModel):
    """Shared shop structure, maintained by the operator."""

    name = models.CharField("Name", max_length=80)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children", verbose_name="Oberkategorie"
    )
    sort = models.PositiveSmallIntegerField("Reihenfolge", default=100)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "parent", "name"], name="category_unique_name", nulls_distinct=False
            )
        ]

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name


class Label(TenantModel):
    """Quality labels such as Bio Suisse or IP-Suisse, maintained by the operator."""

    name = models.CharField("Name", max_length=60)

    class Meta:
        ordering = ["name"]
        verbose_name = "Label"
        verbose_name_plural = "Labels"
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="label_unique_name")]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def visible(self, tenant):
        """What customers may see: active products of active suppliers with at least one active variant."""
        return self.filter(
            tenant=tenant, is_active=True, supplier__status="active", variants__is_active=True
        ).distinct()


class Product(TenantModel):
    supplier = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="products")
    name = models.CharField("Bezeichnung", max_length=120)
    description = models.TextField("Beschreibung", blank=True)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products", verbose_name="Kategorie"
    )
    labels = models.ManyToManyField(Label, blank=True, related_name="products", verbose_name="Labels")
    origin = models.CharField("Herkunft", max_length=120, blank=True, help_text="z.B. Liestal BL")
    temperature = models.CharField(
        "Lagerung/Transport", max_length=16, choices=Temperature.choices, default=Temperature.AMBIENT
    )
    shelf_life_days = models.PositiveSmallIntegerField(
        "Haltbarkeit (Tage)", null=True, blank=True, help_text="Mindesthaltbarkeit ab Lieferung"
    )
    lead_time_days = models.PositiveSmallIntegerField(
        "Vorlaufzeit (Tage)", default=1, help_text="So viele Tage vor Lieferung muss bestellt sein"
    )
    allergens = ArrayField(
        models.CharField(max_length=20, choices=ALLERGENS), blank=True, default=list, verbose_name="Allergene"
    )
    available_months = ArrayField(
        models.PositiveSmallIntegerField(choices=MONTHS),
        blank=True,
        default=list,
        verbose_name="Saison",
        help_text="Leer = ganzjährig",
    )
    image = models.ImageField("Bild", upload_to="products/", blank=True)
    thumbnail = models.ImageField(upload_to="products/thumbs/", blank=True, editable=False)
    is_active = models.BooleanField("Im Shop sichtbar", default=True)
    search_vector = SearchVectorField(null=True, editable=False)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Artikel"
        verbose_name_plural = "Artikel"
        indexes = [
            GinIndex(fields=["search_vector"], name="product_search_idx"),
            GinIndex(fields=["name"], name="product_name_trgm", opclasses=["gin_trgm_ops"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        image_changed = self._image_changed()
        if image_changed and self.image:
            self._process_image()
        super().save(*args, **kwargs)
        self.update_search_vector()

    def _image_changed(self):
        if not self.pk:
            return bool(self.image)
        old = type(self).objects.filter(pk=self.pk).values_list("image", flat=True).first()
        return (old or "") != (self.image.name or "")

    def _process_image(self):
        """Normalise uploads: strip metadata, max 1200 px, plus a 400 px thumbnail (fast pages)."""
        with Image.open(self.image) as img:
            img = img.convert("RGB")
            large = img.copy()
            large.thumbnail((1200, 1200))
            thumb = img.copy()
            thumb.thumbnail((400, 400))
        base = (self.image.name.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "bild")[:40]
        for target, picture, size in ((self.image, large, "l"), (self.thumbnail, thumb, "s")):
            buf = BytesIO()
            picture.save(buf, "WEBP", quality=82)
            target.save(f"{base}-{size}.webp", ContentFile(buf.getvalue()), save=False)

    def update_search_vector(self):
        category = self.category
        parts = [
            (self.name, "A"),
            (
                " ".join(
                    filter(
                        None,
                        [
                            category.name if category else "",
                            category.parent.name if category and category.parent_id else "",
                        ],
                    )
                ),
                "B",
            ),
            (self.supplier.name, "B"),
            (self.origin, "C"),
            (self.description, "D"),
        ]
        vector = None
        for text, weight in parts:
            part = SearchVector(Value(text or ""), weight=weight, config="german")
            vector = part if vector is None else vector + part
        type(self).objects.filter(pk=self.pk).update(search_vector=vector)

    @property
    def allergen_labels(self):
        return [ALLERGEN_LABELS.get(a, a) for a in self.allergens]

    @property
    def season_label(self):
        if not self.available_months:
            return ""
        names = dict(MONTHS)
        return ", ".join(names[m] for m in sorted(self.available_months))

    @property
    def in_season(self):
        return not self.available_months or timezone.localdate().month in self.available_months


class Variant(models.Model):
    """A sellable unit of a product, e.g. «Kartoffeln 2,5 kg»."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField("Variante", max_length=60, help_text="z.B. 500 g, Kiste 10 kg")
    unit = models.CharField("Einheit", max_length=10, choices=Unit.choices, default=Unit.PIECE)
    sku = models.CharField("Artikelnummer", max_length=40, blank=True)
    customer_price = models.DecimalField(
        "Kundenpreis (CHF)", max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.05"))]
    )
    vat_rate = models.CharField("MWST", max_length=4, choices=VatRate.choices, default=VatRate.REDUCED)
    min_qty = models.DecimalField(
        "Mindestmenge",
        max_digits=8,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    qty_step = models.DecimalField(
        "Bestellschritt",
        max_digits=8,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="z.B. 0.5 für halbe Kilos",
    )
    stock = models.DecimalField(
        "Bestand", max_digits=10, decimal_places=2, null=True, blank=True, help_text="Leer = keine Bestandsführung"
    )
    is_active = models.BooleanField("Aktiv", default=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "customer_price"]
        verbose_name = "Variante"
        verbose_name_plural = "Varianten"
        constraints = [
            models.UniqueConstraint(fields=["product", "name"], name="variant_unique_name"),
        ]

    def __str__(self):
        return f"{self.product.name} – {self.name}"

    @property
    def vat_label(self):
        if self.vat_rate == VatRate.NONE:
            return "ohne MWST"
        return f"inkl. {self.vat_rate.replace('.', ',')} % MWST"

    @property
    def sold_out(self):
        return self.stock is not None and self.stock < self.min_qty
