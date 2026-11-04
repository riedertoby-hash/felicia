import hashlib
import logging
import urllib.request

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class PwnedPasswordValidator:
    """Rejects passwords found in known data leaks (haveibeenpwned, k-anonymity:
    only the first 5 hash characters leave the server). Fails open if the service is down."""

    url = "https://api.pwnedpasswords.com/range/"

    def validate(self, password, user=None):
        if not getattr(settings, "PWNED_PASSWORDS_CHECK", True):
            return
        digest = hashlib.sha1(password.encode()).hexdigest().upper()  # noqa: S324 - required by API
        prefix, suffix = digest[:5], digest[5:]
        try:
            req = urllib.request.Request(self.url + prefix, headers={"Add-Padding": "true"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310
                body = resp.read().decode()
        except Exception:
            logger.warning("Passwort-Leak-Prüfung nicht erreichbar, übersprungen.")
            return
        for line in body.splitlines():
            hash_suffix, _, count = line.partition(":")
            if hash_suffix == suffix and int(count or 0) > 0:
                raise ValidationError(
                    "Dieses Passwort ist aus Datenlecks bekannt. Bitte ein anderes wählen.",
                    code="password_pwned",
                )

    def get_help_text(self):
        return "Das Passwort darf nicht aus bekannten Datenlecks stammen."
