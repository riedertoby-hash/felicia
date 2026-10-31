from django.core.checks import Warning as CheckWarning
from django.core.checks import register
from django.db import connection


@register("database", deploy=True)
def rls_effective(app_configs, databases=None, **kwargs):
    """Row-level security has no effect for superusers or roles with BYPASSRLS."""
    if not databases or "default" not in databases:
        return []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - no database available during the check
        return []
    if row and row[0]:
        return [
            CheckWarning(
                "Die App verbindet sich als Datenbank-Superuser – die Datensperre (Row-Level-Security) wirkt nicht.",
                hint="Eigenen App-Benutzer ohne SUPERUSER/BYPASSRLS verwenden (siehe deploy/db-init.sh).",
                id="felicia.W001",
            )
        ]
    return []
