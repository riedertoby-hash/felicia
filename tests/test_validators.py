import pytest
from django.core.exceptions import ValidationError

from apps.core.validators import mask_iban, normalize_swiss_uid, validate_iban, validate_swiss_uid


def test_valid_swiss_iban():
    validate_iban("CH93 0076 2011 6238 5295 7")


@pytest.mark.parametrize("iban", ["CH93 0076 2011 6238 5295 8", "CH93", "XX00", "CH9300762011623852957000"])
def test_invalid_iban(iban):
    with pytest.raises(ValidationError):
        validate_iban(iban)


def test_mask_iban():
    assert mask_iban("CH9300762011623852957") == "CH93 •••• •••• 2957"


def _uid_with_check(base8):
    weights = [5, 4, 3, 2, 7, 6, 5, 4]
    check = 11 - sum(int(d) * w for d, w in zip(base8, weights, strict=True)) % 11
    return base8 + str(0 if check == 11 else check), check


def test_swiss_uid_check_digit():
    for base in ("10912345", "11628171", "12345678"):
        full, check = _uid_with_check(base)
        if check == 10:
            continue
        uid = f"CHE-{full[:3]}.{full[3:6]}.{full[6:]} MWST"
        validate_swiss_uid(uid)
        assert normalize_swiss_uid(uid.replace("-", "").replace(".", "")) == uid
        wrong = full[:8] + str((int(full[8]) + 1) % 10)
        with pytest.raises(ValidationError):
            validate_swiss_uid(f"CHE-{wrong[:3]}.{wrong[3:6]}.{wrong[6:]}")
