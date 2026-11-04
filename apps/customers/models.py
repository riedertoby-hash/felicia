from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_swiss_zip
from apps.suppliers.models import CANTONS


class CustomerProfile(TimeStampedModel):
    class Type(models.TextChoices):
        BUSINESS = "business", "Betrieb"
        PRIVATE = "private", "Privat"

    organization = models.OneToOneField("orgs.Organization", on_delete=models.CASCADE, related_name="customer_profile")
    customer_type = models.CharField("Kundenart", max_length=16, choices=Type.choices, default=Type.BUSINESS)
    phone = models.CharField("Telefon", max_length=30, blank=True)
    billing_email = models.EmailField("E-Mail für Rechnungen", blank=True)
    vat_number = models.CharField("MWST-Nummer", max_length=20, blank=True)
    billing_name = models.CharField("Rechnung an", max_length=200, blank=True)
    billing_street = models.CharField("Strasse und Nr.", max_length=200, blank=True)
    billing_zip_code = models.CharField("PLZ", max_length=4, blank=True, validators=[validate_swiss_zip])
    billing_city = models.CharField("Ort", max_length=100, blank=True)

    class Meta:
        verbose_name = "Kunden-Profil"
        verbose_name_plural = "Kunden-Profile"

    def __str__(self):
        return str(self.organization)


class Address(TimeStampedModel):
    organization = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField("Bezeichnung", max_length=80, help_text="z.B. Restaurant, Lager")
    recipient = models.CharField("Empfänger", max_length=200)
    street = models.CharField("Strasse und Nr.", max_length=200)
    zip_code = models.CharField("PLZ", max_length=4, validators=[validate_swiss_zip])
    city = models.CharField("Ort", max_length=100)
    canton = models.CharField("Kanton", max_length=2, choices=CANTONS, blank=True)
    delivery_notes = models.CharField(
        "Hinweis für die Lieferung", max_length=300, blank=True, help_text="z.B. Hintereingang, Anlieferung bis 10 Uhr"
    )
    is_default = models.BooleanField("Standard-Lieferadresse", default=False)

    class Meta:
        ordering = ["-is_default", "label"]
        verbose_name = "Lieferadresse"
        verbose_name_plural = "Lieferadressen"

    def __str__(self):
        return f"{self.label}: {self.street}, {self.zip_code} {self.city}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(organization=self.organization).exclude(pk=self.pk).update(is_default=False)
