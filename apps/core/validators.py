import re

from django.core.exceptions import ValidationError

IBAN_LENGTHS = {"CH": 21, "LI": 21, "DE": 22, "AT": 20, "FR": 27, "IT": 27}


def normalize_iban(value):
    return re.sub(r"\s+", "", value or "").upper()


def validate_iban(value):
    iban = normalize_iban(value)
    country = iban[:2]
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", iban):
        raise ValidationError("Ungültige IBAN.")
    if country in IBAN_LENGTHS and len(iban) != IBAN_LENGTHS[country]:
        raise ValidationError("IBAN hat die falsche Länge.")
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    if int(digits) % 97 != 1:
        raise ValidationError("IBAN-Prüfziffer stimmt nicht.")


def format_iban(value):
    iban = normalize_iban(value)
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def mask_iban(value):
    iban = normalize_iban(value)
    if len(iban) < 8:
        return "••••"
    return f"{iban[:4]} •••• •••• {iban[-4:]}"


UID_RE = re.compile(r"^CHE-?(\d{3})\.?(\d{3})\.?(\d{3})(\s*(MWST|TVA|IVA))?$", re.I)


def validate_swiss_uid(value):
    """Swiss company UID (CHE-123.456.789 MWST) incl. mod-11 check digit."""
    match = UID_RE.match((value or "").strip())
    if not match:
        raise ValidationError("Format: CHE-123.456.789 MWST")
    digits = [int(d) for d in "".join(match.groups()[:3])]
    weights = [5, 4, 3, 2, 7, 6, 5, 4]
    check = 11 - sum(d * w for d, w in zip(digits[:8], weights, strict=True)) % 11
    if check == 11:
        check = 0
    if check == 10 or check != digits[8]:
        raise ValidationError("UID-Prüfziffer stimmt nicht.")


def normalize_swiss_uid(value):
    match = UID_RE.match((value or "").strip())
    if not match:
        return value
    a, b, c = match.groups()[:3]
    return f"CHE-{a}.{b}.{c} MWST"


SWISS_ZIP_RE = re.compile(r"^\d{4}$")


def validate_swiss_zip(value):
    if not SWISS_ZIP_RE.match(value or ""):
        raise ValidationError("Postleitzahl: 4 Ziffern.")
