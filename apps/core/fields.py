from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models


def _fernet():
    return MultiFernet([Fernet(k.encode()) for k in settings.FIELD_ENCRYPTION_KEYS])


class EncryptedCharField(models.TextField):
    """Stores text encrypted at rest (Fernet / AES-128-CBC + HMAC). Not searchable."""

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Verschlüsselter Wert kann nicht gelesen werden (Schlüssel?).") from exc

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _fernet().encrypt(value.encode()).decode()
