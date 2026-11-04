from django import forms

from apps.orgs.models import Role

from .models import MarketplaceSettings, SupplierTerms


class SettingsForm(forms.ModelForm):
    mfa_required_roles = forms.MultipleChoiceField(
        label="Zwei-Faktor-Anmeldung ist Pflicht für", required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = MarketplaceSettings
        fields = [
            "contact_email",
            "default_commission_percent",
            "base_fee_enabled",
            "base_fee_monthly",
            "supplier_approval_required",
            "mfa_required_roles",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["base_fee_monthly"].widget.attrs["data-show-if"] = "base_fee_enabled=on"
        roles = Role.objects.filter(tenant__isnull=True) | Role.objects.filter(tenant=self.instance.tenant)
        self.fields["mfa_required_roles"].choices = [
            (r.key, f"{r.get_kind_display()}: {r.name}") for r in roles.order_by("kind", "sort")
        ]


class TermsForm(forms.ModelForm):
    class Meta:
        model = SupplierTerms
        fields = ["commission_percent", "base_fee_monthly", "internal_note"]
        widgets = {"internal_note": forms.Textarea(attrs={"rows": 3})}
