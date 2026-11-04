import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

SCOPES = [
    ("orders.read", "Bestellungen lesen"),
    ("orders.write", "Bestellstatus setzen"),
    ("catalog.read", "Artikel lesen"),
    ("stock.write", "Bestand ändern"),
    ("prices.write", "Preise ändern"),
    ("invoices.read", "Rechnungen lesen"),
]
SCOPE_PERMISSION = {  # the creator must hold this role permission to grant the scope
    "orders.read": "orders.view",
    "orders.write": "orders.manage",
    "catalog.read": "catalog.view",
    "stock.write": "catalog.edit",
    "prices.write": "prices.edit",
    "invoices.read": "finance.view",
}


class ApiKey(models.Model):
    """Secret token for a supplier's own systems. Only a hash is stored; the key is shown once."""

    organization = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField("Bezeichnung", max_length=80, help_text="z.B. Warenwirtschaft")
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def hash(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, *, organization, name, scopes, user):
        raw = "fel_" + secrets.token_urlsafe(32)
        key = cls.objects.create(
            organization=organization,
            name=name,
            prefix=raw[:12],
            key_hash=cls.hash(raw),
            scopes=scopes,
            created_by=user,
        )
        return key, raw

    @classmethod
    def authenticate(cls, raw):
        if not raw or not raw.startswith("fel_"):
            return None
        key = (
            cls.objects.select_related("organization__tenant")
            .filter(key_hash=cls.hash(raw), revoked_at__isnull=True)
            .first()
        )
        if key is None or key.organization.status != "active":
            return None
        cls.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return key
