from allauth.account.forms import SignupForm as AllauthSignupForm
from django import forms
from django.db import transaction

from apps.orgs.models import Organization
from apps.orgs.services import create_organization


class SignupForm(AllauthSignupForm):
    ACCOUNT_CHOICES = [
        ("customer_business", "Ich kaufe für einen Betrieb ein (Gastronomie, Handel …)"),
        ("customer_private", "Ich kaufe privat ein"),
        ("supplier", "Ich bin Produzent/Lieferant und möchte verkaufen"),
    ]

    account_type = forms.ChoiceField(
        label="Wofür nutzen Sie den Marktplatz?", choices=ACCOUNT_CHOICES, widget=forms.RadioSelect
    )
    first_name = forms.CharField(label="Vorname", max_length=150)
    last_name = forms.CharField(label="Nachname", max_length=150)
    organization_name = forms.CharField(
        label="Name des Betriebs",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={"data-show-if": "account_type!=customer_private"}),
    )
    accept_terms = forms.BooleanField(label="Ich akzeptiere die AGB und die Datenschutzerklärung.")

    field_order = [
        "account_type",
        "organization_name",
        "first_name",
        "last_name",
        "email",
        "password1",
        "password2",
        "accept_terms",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization_name"].show_optional = False

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("account_type")
        if kind in ("supplier", "customer_business") and not cleaned.get("organization_name"):
            self.add_error("organization_name", "Bitte den Namen des Betriebs angeben.")
        return cleaned

    @transaction.atomic
    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.save(update_fields=["first_name", "last_name"])
        kind = self.cleaned_data["account_type"]
        if kind == "supplier":
            create_organization(
                tenant=request.tenant,
                kind=Organization.Kind.SUPPLIER,
                name=self.cleaned_data["organization_name"],
                owner=user,
            )
        else:
            business = kind == "customer_business"
            create_organization(
                tenant=request.tenant,
                kind=Organization.Kind.CUSTOMER,
                name=self.cleaned_data["organization_name"] if business else user.get_full_name(),
                owner=user,
                customer_type="business" if business else "private",
            )
        return user
