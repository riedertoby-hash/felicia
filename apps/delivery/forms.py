from django import forms
from django.forms import inlineformset_factory

from apps.suppliers.models import CANTONS

from .models import WEEKDAYS, DeliveryOption, DeliveryZone, FeeTier, parse_zip_list


class OptionForm(forms.ModelForm):
    weekdays = forms.TypedMultipleChoiceField(
        label="Liefer-/Abholtage", choices=WEEKDAYS, coerce=int, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = DeliveryOption
        fields = ["kind", "name", "weekdays", "cutoff_time", "lead_days", "carrier_name", "notes", "is_active"]
        widgets = {
            "kind": forms.RadioSelect,
            "cutoff_time": forms.TimeInput(attrs={"type": "time"}),
            "carrier_name": forms.TextInput(attrs={"data-show-if": "kind=carrier"}),
        }


class ZoneForm(forms.ModelForm):
    cantons = forms.MultipleChoiceField(
        label="Ganze Kantone",
        choices=CANTONS,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "cantons"}),
    )

    class Meta:
        model = DeliveryZone
        fields = ["name", "zip_codes", "cantons", "min_order_value"]
        widgets = {"zip_codes": forms.Textarea(attrs={"rows": 2})}

    def clean_zip_codes(self):
        value = self.cleaned_data.get("zip_codes", "")
        parse_zip_list(value)
        return value

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("zip_codes") or "").strip() and not cleaned.get("cantons"):
            raise forms.ValidationError("Bitte Postleitzahlen oder Kantone angeben.")
        return cleaned


FeeTierFormSet = inlineformset_factory(DeliveryZone, FeeTier, fields=["from_value", "fee"], extra=1, can_delete=True)
