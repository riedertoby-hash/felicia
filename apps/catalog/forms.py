from decimal import Decimal, InvalidOperation

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from . import pricing
from .models import ALLERGENS, MONTHS, Category, Label, Product, Variant


class ProductForm(forms.ModelForm):
    allergens = forms.TypedMultipleChoiceField(
        label="Allergene", choices=ALLERGENS, required=False, widget=forms.CheckboxSelectMultiple
    )
    available_months = forms.TypedMultipleChoiceField(
        label="Saison",
        choices=MONTHS,
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Nichts angekreuzt = ganzjährig",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "description",
            "origin",
            "temperature",
            "shelf_life_days",
            "lead_time_days",
            "labels",
            "allergens",
            "available_months",
            "image",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "temperature": forms.RadioSelect,
            "labels": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(tenant=tenant).select_related("parent")
        self.fields["category"].required = True
        self.fields["category"].empty_label = "Bitte wählen"
        self.fields["labels"].queryset = Label.objects.filter(tenant=tenant)

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "size") and image.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Bild max. 5 MB.")
        return image


class VariantForm(forms.ModelForm):
    supplier_price = forms.DecimalField(
        label="Sie erhalten (CHF)", max_digits=9, decimal_places=2, required=False, min_value=Decimal("0.01")
    )
    price_basis = forms.ChoiceField(
        choices=[("customer", "customer"), ("supplier", "supplier")],
        initial="customer",
        widget=forms.HiddenInput(attrs={"data-price": "basis"}),
    )

    class Meta:
        model = Variant
        fields = ["name", "unit", "sku", "customer_price", "vat_rate", "min_qty", "qty_step", "stock", "is_active"]

    def __init__(self, *args, commission, can_edit_prices, **kwargs):
        super().__init__(*args, **kwargs)
        self.commission = commission
        self.fields["customer_price"].widget.attrs.update({"data-price": "customer", "step": "0.05"})
        self.fields["supplier_price"].widget.attrs.update({"data-price": "supplier", "step": "0.01"})
        self.fields["customer_price"].required = False
        self.fields["customer_price"].show_optional = False
        self.fields["supplier_price"].show_optional = False
        if self.instance.pk and self.instance.customer_price:
            self.fields["supplier_price"].initial = pricing.supplier_net(self.instance.customer_price, commission)
        if not can_edit_prices:
            for name in ("customer_price", "supplier_price", "vat_rate"):
                self.fields[name].disabled = True

    def clean(self):
        cleaned = super().clean()
        if self.fields["customer_price"].disabled:
            return cleaned
        basis = cleaned.get("price_basis") or "customer"
        if basis == "supplier" and cleaned.get("supplier_price"):
            cleaned["customer_price"] = pricing.customer_price_from_supplier(cleaned["supplier_price"], self.commission)
        elif cleaned.get("customer_price"):
            cleaned["customer_price"] = pricing.round_5_rappen(cleaned["customer_price"])
        if not cleaned.get("customer_price") and not cleaned.get("DELETE") and self.has_changed():
            self.add_error("customer_price", "Bitte einen Preis angeben.")
        self.instance.customer_price = cleaned.get("customer_price")
        return cleaned


class BaseVariantFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        active = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not active:
            raise forms.ValidationError("Mindestens eine Variante mit Preis erfassen.")
        names = [f.cleaned_data.get("name", "").strip().lower() for f in active]
        if len(names) != len(set(names)):
            raise forms.ValidationError("Jede Variante braucht einen eigenen Namen.")


VariantFormSet = inlineformset_factory(
    Product,
    Variant,
    form=VariantForm,
    formset=BaseVariantFormSet,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=False,
)


class CsvUploadForm(forms.Form):
    file = forms.FileField(label="CSV-Datei", help_text="Max. 1 MB. Vorlage herunterladen, ausfüllen, hochladen.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 1024 * 1024:
            raise forms.ValidationError("Datei max. 1 MB.")
        raw = f.read()
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise forms.ValidationError("Datei konnte nicht gelesen werden (Zeichensatz).")


def parse_decimal(value):
    value = (value or "").strip().replace("'", "").replace(" ", "")
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"«{value}» ist keine Zahl") from exc
