from django import forms
from django.contrib.auth import password_validation

from .models import Role


# Pre-selected role when inviting: the everyday role, never the owner.
DEFAULT_INVITE_ROLE = {"operator": "operator_staff", "supplier": "supplier_clerk", "customer": "customer_buyer"}


class InviteForm(forms.Form):
    email = forms.EmailField(label="E-Mail")
    role = forms.ModelChoiceField(label="Rolle", queryset=Role.objects.none(), empty_label=None)

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        roles = Role.objects.for_org(org)
        self.fields["role"].queryset = roles
        self.fields["role"].initial = roles.filter(key=DEFAULT_INVITE_ROLE.get(org.kind)).first()


class RoleForm(forms.Form):
    role = forms.ModelChoiceField(
        label="Rolle",
        queryset=Role.objects.none(),
        empty_label=None,
        widget=forms.Select(attrs={"data-autosubmit": "", "aria-label": "Rolle"}),
    )

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.for_org(org)


class InviteSignupForm(forms.Form):
    first_name = forms.CharField(label="Vorname", max_length=150)
    last_name = forms.CharField(label="Nachname", max_length=150)
    password1 = forms.CharField(label="Passwort", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(
        label="Passwort wiederholen", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    accept_terms = forms.BooleanField(label="Ich akzeptiere die AGB und die Datenschutzerklärung.")

    def __init__(self, *args, email, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Die Passwörter stimmen nicht überein.")
        if p1:
            from apps.accounts.models import User

            probe = User(
                email=self.email, first_name=cleaned.get("first_name", ""), last_name=cleaned.get("last_name", "")
            )
            try:
                password_validation.validate_password(p1, probe)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned
