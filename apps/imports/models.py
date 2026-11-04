from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class ImportBatch(TenantModel):
    """One import run by the operator; remembers what was created so invitations can be sent later."""

    class Kind(models.TextChoices):
        SUPPLIERS = "suppliers", "Lieferanten"
        CUSTOMERS = "customers", "Kunden"
        PRODUCTS = "products", "Artikel"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    filename = models.CharField(max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    organizations = models.ManyToManyField("orgs.Organization", blank=True, related_name="+")
    invitations_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.filename}"
