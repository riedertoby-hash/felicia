from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Append-only record of security- and business-relevant changes.
    Updates and deletes are blocked by a database trigger (see migration)."""

    tenant = models.ForeignKey("core.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    organization = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_label = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_label = models.CharField(max_length=254, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Protokolleintrag"
        verbose_name_plural = "Protokoll"
        indexes = [models.Index(fields=["tenant", "-created_at"]), models.Index(fields=["organization", "-created_at"])]

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.actor_label} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise RuntimeError("Protokolleinträge sind unveränderlich.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Protokolleinträge können nicht gelöscht werden.")

    @property
    def label(self):
        return ACTION_LABELS.get(self.action, self.action)


ACTION_LABELS = {
    "auth.login": "Anmeldung",
    "auth.login_failed": "Fehlgeschlagene Anmeldung",
    "auth.logout": "Abmeldung",
    "auth.password_changed": "Passwort geändert",
    "auth.password_reset": "Passwort zurückgesetzt",
    "auth.mfa_added": "Zwei-Faktor-Methode hinzugefügt",
    "auth.mfa_removed": "Zwei-Faktor-Methode entfernt",
    "org.created": "Organisation erstellt",
    "org.updated": "Profil geändert",
    "org.bank_updated": "Bankverbindung geändert",
    "org.approved": "Lieferant freigeschaltet",
    "org.blocked": "Organisation gesperrt",
    "org.unblocked": "Sperre aufgehoben",
    "org.terms_updated": "Konditionen (Provision/Gebühr) geändert",
    "member.added": "Mitglied hinzugefügt",
    "member.role_changed": "Rolle geändert",
    "member.removed": "Mitglied entfernt",
    "invite.sent": "Einladung verschickt",
    "invite.accepted": "Einladung angenommen",
    "invite.revoked": "Einladung zurückgezogen",
    "settings.updated": "Marktplatz-Einstellungen geändert",
    "address.saved": "Adresse gespeichert",
    "address.deleted": "Adresse gelöscht",
}
