from django.db import models

from apps.core.fields import EncryptedCharField
from apps.core.models import TimeStampedModel
from apps.core.validators import format_iban, mask_iban, validate_swiss_zip

CANTONS = [(c, c) for c in ("AG AI AR BE BL BS FR GE GL GR JU LU NE NW OW SG SH SO SZ TG TI UR VD VS ZG ZH".split())]


class SupplierProfile(TimeStampedModel):
    class Channel(models.TextChoices):
        EMAIL = "email", "E-Mail"
        SMS = "sms", "SMS (Kurzmeldung)"
        PUSH = "push", "Push-Nachricht aufs Handy"
        WEBHOOK = "webhook", "Schnittstelle (Webhook)"

    class Mode(models.TextChoices):
        IMMEDIATE = "immediate", "Sofort bei jeder Bestellung"
        DAILY = "daily", "Einmal täglich als Zusammenzug"
        BOTH = "both", "Sofort und täglicher Zusammenzug"

    organization = models.OneToOneField("orgs.Organization", on_delete=models.CASCADE, related_name="supplier_profile")
    # Stammdaten
    legal_name = models.CharField("Firmenname (rechtlich)", max_length=200, blank=True)
    description = models.TextField("Über uns", blank=True, help_text="Erscheint auf Ihrer Seite im Shop.")
    logo = models.ImageField("Logo", upload_to="logos/", blank=True)
    website = models.URLField("Webseite", blank=True)
    contact_email = models.EmailField("Kontakt-E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=30, blank=True)
    street = models.CharField("Strasse und Nr.", max_length=200, blank=True)
    zip_code = models.CharField("PLZ", max_length=4, blank=True, validators=[validate_swiss_zip])
    city = models.CharField("Ort", max_length=100, blank=True)
    canton = models.CharField("Kanton", max_length=2, choices=CANTONS, blank=True)
    # MWST
    vat_registered = models.BooleanField("MWST-pflichtig", default=False)
    vat_number = models.CharField("MWST-Nummer", max_length=20, blank=True, help_text="CHE-123.456.789 MWST")
    # Abholung
    pickup_same_as_address = models.BooleanField("Abholung an Firmenadresse", default=True)
    pickup_street = models.CharField("Abholung: Strasse", max_length=200, blank=True)
    pickup_zip_code = models.CharField("Abholung: PLZ", max_length=4, blank=True, validators=[validate_swiss_zip])
    pickup_city = models.CharField("Abholung: Ort", max_length=100, blank=True)
    opening_hours = models.TextField("Öffnungs- und Abholzeiten", blank=True)
    # Bank (encrypted)
    account_holder = models.CharField("Kontoinhaber", max_length=200, blank=True)
    iban = EncryptedCharField("IBAN", blank=True)
    # Benachrichtigung
    notify_channel = models.CharField("Kanal", max_length=16, choices=Channel.choices, default=Channel.EMAIL)
    notify_mode = models.CharField("Zeitpunkt", max_length=16, choices=Mode.choices, default=Mode.IMMEDIATE)
    notify_digest_time = models.TimeField("Zusammenzug um", default="17:00")
    notify_email = models.EmailField("E-Mail für Bestellungen", blank=True, help_text="Leer = Kontakt-E-Mail")
    notify_phone = models.CharField("Handy für SMS", max_length=30, blank=True)
    webhook_url = models.URLField("Webhook-Adresse", blank=True)

    class Meta:
        verbose_name = "Lieferanten-Profil"
        verbose_name_plural = "Lieferanten-Profile"

    def __str__(self):
        return str(self.organization)

    @property
    def iban_masked(self):
        return mask_iban(self.iban) if self.iban else ""

    @property
    def iban_formatted(self):
        return format_iban(self.iban) if self.iban else ""

    def completeness(self):
        """Checklist shown on the dashboard so suppliers know what's missing."""
        return [
            ("Adresse", bool(self.street and self.zip_code and self.city)),
            ("Kontakt", bool(self.contact_email or self.phone)),
            ("Beschreibung", bool(self.description)),
            ("Bankverbindung", bool(self.iban and self.account_holder)),
        ]
