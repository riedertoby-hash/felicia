"""ISO 11649 creditor reference («RF…»), usable with a normal IBAN on the Swiss QR-bill."""

import re


def _to_digits(text):
    return "".join(str(int(c, 36)) for c in text)


def creditor_reference(base):
    base = re.sub(r"[^A-Z0-9]", "", base.upper())[:21]
    check = 98 - int(_to_digits(base + "RF00")) % 97
    return f"RF{check:02d}{base}"


def is_valid(ref):
    ref = ref.replace(" ", "").upper()
    return ref.startswith("RF") and int(_to_digits(ref[4:] + ref[:4])) % 97 == 1
