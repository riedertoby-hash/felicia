from django import forms

from apps.core.validators import normalize_iban, normalize_swiss_uid, validate_iban, validate_swiss_uid

from .models import SupplierProfile


class ProfileForm(forms.ModelForm):
    name = forms.CharField(label="Name im Shop", max_length=160)

    class Meta:
        model = SupplierProfile
        fields = [
            "legal_name",
            "description",
            "logo",
            "website",
            "contact_email",
            "phone",
            "street",
            "zip_code",
            "city",
            "canton",
            "vat_registered",
            "vat_number",
            "pickup_same_as_address",
            "pickup_street",
            "pickup_zip_code",
            "pickup_city",
            "opening_hours",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "opening_hours": forms.Textarea(attrs={"rows": 3}),
            "vat_number": forms.TextInput(attrs={"data-show-if": "vat_registered=on"}),
            "pickup_street": forms.TextInput(attrs={"data-show-if": "pickup_same_as_address=off"}),
            "pickup_zip_code": forms.TextInput(attrs={"data-show-if": "pickup_same_as_address=off"}),
            "pickup_city": forms.TextInput(attrs={"data-show-if": "pickup_same_as_address=off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].initial = self.instance.organization.name
        self.order_fields(["name"] + self.Meta.fields)

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "size") and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Logo max. 2 MB.")
        return logo

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("vat_registered"):
            number = cleaned.get("vat_number", "")
            if not number:
                self.add_error("vat_number", "Bitte MWST-Nummer angeben.")
            else:
                try:
                    validate_swiss_uid(number)
                    cleaned["vat_number"] = normalize_swiss_uid(number)
                except forms.ValidationError as exc:
                    self.add_error("vat_number", exc)
        if not cleaned.get("pickup_same_as_address"):
            for f in ("pickup_street", "pickup_zip_code", "pickup_city"):
                if not cleaned.get(f):
                    self.add_error(f, "Bitte Abholadresse angeben.")
        return cleaned

    def save(self, commit=True):
        profile = super().save(commit)
        org = profile.organization
        if org.name != self.cleaned_data["name"]:
            org.name = self.cleaned_data["name"]
            org.save(update_fields=["name", "updated_at"])
        return profile


class BankForm(forms.ModelForm):
    class Meta:
        model = SupplierProfile
        fields = ["account_holder", "iban"]
        widgets = {"iban": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "CH93 0076 2011 6238 5295 7"})}

    def clean_iban(self):
        iban = self.cleaned_data.get("iban", "")
        if iban:
            validate_iban(iban)
            return normalize_iban(iban)
        # The stored IBAN is never sent to the browser; an empty field keeps it.
        return self.instance.iban


class NotificationForm(forms.ModelForm):
    class Meta:
        model = SupplierProfile
        fields = ["notify_channel", "notify_mode", "notify_digest_time", "notify_email", "notify_phone", "webhook_url"]
        widgets = {
            "notify_channel": forms.RadioSelect,
            "notify_mode": forms.RadioSelect,
            "notify_digest_time": forms.TimeInput(attrs={"type": "time", "data-show-if": "notify_mode!=immediate"}),
            "notify_phone": forms.TextInput(attrs={"data-show-if": "notify_channel=sms"}),
            "webhook_url": forms.URLInput(attrs={"data-show-if": "notify_channel=webhook"}),
        }

    def clean(self):
        cleaned = super().clean()
        channel = cleaned.get("notify_channel")
        if channel == "sms" and not cleaned.get("notify_phone"):
            self.add_error("notify_phone", "Für SMS bitte eine Handynummer angeben.")
        if channel == "webhook":
            url = cleaned.get("webhook_url", "")
            if not url:
                self.add_error("webhook_url", "Bitte Webhook-Adresse angeben.")
            elif not url.startswith("https://"):
                self.add_error("webhook_url", "Nur https-Adressen sind erlaubt.")
        return cleaned
