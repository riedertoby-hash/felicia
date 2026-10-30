from decimal import Decimal

from django import forms


class QuantityForm(forms.Form):
    quantity = forms.DecimalField(min_value=Decimal("0"), max_digits=8, decimal_places=2)
