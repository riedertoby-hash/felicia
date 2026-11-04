from django import forms

from apps.operator.models import MarketplaceSettings

from .models import BillingSettings, CustomerTerms


class BillingSettingsForm(forms.ModelForm):
    class Meta:
        model = BillingSettings
        fields = [
            "invoice_mode",
            "payment_terms_days",
            "footer",
            "reminders_enabled",
            "first_reminder_days",
            "reminder_interval_days",
            "max_reminder_level",
            "reminder_fee",
            "account_debtors",
            "account_revenue",
            "account_bank",
            "account_fees",
        ]
        widgets = {
            "invoice_mode": forms.RadioSelect,
            "footer": forms.Textarea(attrs={"rows": 3}),
            "first_reminder_days": forms.NumberInput(attrs={"data-show-if": "s-reminders_enabled=on"}),
            "reminder_interval_days": forms.NumberInput(attrs={"data-show-if": "s-reminders_enabled=on"}),
            "max_reminder_level": forms.NumberInput(attrs={"data-show-if": "s-reminders_enabled=on"}),
            "reminder_fee": forms.NumberInput(attrs={"data-show-if": "s-reminders_enabled=on"}),
        }


class CustomerTermsForm(forms.ModelForm):
    class Meta:
        model = CustomerTerms
        fields = ["customer", "invoice_mode", "payment_terms_days"]

    def __init__(self, *args, customers, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = customers
        self.fields["customer"].label = "Kunde"
        self.fields["invoice_mode"].choices = [("", "– wie Standard –"), *self.fields["invoice_mode"].choices[1:]]


class OperatorIssuerForm(forms.ModelForm):
    class Meta:
        model = MarketplaceSettings
        fields = [
            "legal_name",
            "street",
            "zip_code",
            "city",
            "iban",
            "vat_registered",
            "vat_number",
            "commission_period",
        ]
        widgets = {
            "iban": forms.TextInput(attrs={"autocomplete": "off"}),
            "vat_number": forms.TextInput(attrs={"data-show-if": "vat_registered=on"}),
        }

    def clean_iban(self):
        from apps.core.validators import normalize_iban, validate_iban

        iban = self.cleaned_data.get("iban", "")
        if iban:
            validate_iban(iban)
            return normalize_iban(iban)
        return iban
