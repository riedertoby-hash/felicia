from django import forms

from .models import Address, CustomerProfile


class ProfileForm(forms.ModelForm):
    name = forms.CharField(label="Name", max_length=160)

    class Meta:
        model = CustomerProfile
        fields = [
            "phone",
            "billing_email",
            "vat_number",
            "billing_name",
            "billing_street",
            "billing_zip_code",
            "billing_city",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].initial = self.instance.organization.name
        self.order_fields(["name"] + self.Meta.fields)
        if self.instance.customer_type == CustomerProfile.Type.PRIVATE:
            del self.fields["vat_number"]

    def save(self, commit=True):
        profile = super().save(commit)
        org = profile.organization
        if org.name != self.cleaned_data["name"]:
            org.name = self.cleaned_data["name"]
            org.save(update_fields=["name", "updated_at"])
        return profile


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ["label", "recipient", "street", "zip_code", "city", "delivery_notes", "is_default"]
