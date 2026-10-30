import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.audit.services import log
from apps.suppliers.models import SupplierProfile
from tests.conftest import give_mfa

pytestmark = pytest.mark.django_db


def test_mfa_enforced_for_required_roles(login, supplier_a, mp_settings):
    mp_settings.mfa_required_roles = ["supplier_owner"]
    mp_settings.save()
    client = login(supplier_a.owner)
    response = client.get(reverse("suppliers:dashboard"))
    assert response.status_code == 302 and response["Location"] == reverse("mfa_index")
    # Roles without the requirement are not affected
    assert login(supplier_a.clerk).get(reverse("suppliers:dashboard")).status_code == 200
    give_mfa(supplier_a.owner)
    assert login(supplier_a.owner).get(reverse("suppliers:dashboard")).status_code == 200


def test_iban_encrypted_at_rest_and_masked(login, supplier_a):
    client = login(supplier_a.owner)
    response = client.post(reverse("suppliers:bank"), {"account_holder": "Hof A", "iban": "CH93 0076 2011 6238 5295 7"})
    assert response.status_code == 302
    with connection.cursor() as cursor:
        cursor.execute("SELECT iban FROM suppliers_supplierprofile WHERE organization_id = %s", [supplier_a.pk])
        raw = cursor.fetchone()[0]
    assert "CH93" not in raw
    assert SupplierProfile.objects.get(organization=supplier_a).iban == "CH9300762011623852957"
    page = client.get(reverse("suppliers:bank")).content.decode()
    assert "CH9300762011623852957" not in page and "2957" in page
    event = AuditEvent.objects.get(action="org.bank_updated")
    assert event.changes["iban"] == ["•••", "•••"]
    # empty field keeps the stored IBAN
    client.post(reverse("suppliers:bank"), {"account_holder": "Hof A AG", "iban": ""})
    assert SupplierProfile.objects.get(organization=supplier_a).iban == "CH9300762011623852957"


def test_audit_log_is_append_only_in_database(supplier_a):
    event = log("org.updated", organization=supplier_a, actor=supplier_a.owner)
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE audit_auditevent SET action = 'x' WHERE id = %s", [event.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_auditevent WHERE id = %s", [event.pk])
    assert AuditEvent.objects.filter(pk=event.pk, action="org.updated").exists()


def test_deleting_user_keeps_audit_trail(supplier_a):
    event = log("org.updated", organization=supplier_a, actor=supplier_a.clerk)
    supplier_a.clerk.delete()
    event.refresh_from_db()
    assert event.actor_id is None and event.actor_label == "clerk@hof-a.ch"


def test_operator_actions_are_logged(login, operator, supplier_a):
    login(operator.admin).post(
        reverse("operator:supplier", args=[supplier_a.pk]), {"commission_percent": "12.5", "base_fee_monthly": ""}
    )
    event = AuditEvent.objects.get(action="org.terms_updated")
    assert event.changes["commission_percent"] == [None, "12.5"]
    assert event.actor == operator.admin


def test_login_is_logged(client, supplier_a):
    client.post(reverse("account_login"), {"login": "owner@hof-a.ch", "password": "falsch-falsch-falsch"})
    assert AuditEvent.objects.filter(action="auth.login_failed", actor=supplier_a.owner).exists()


def test_security_headers(client, tenant):
    response = client.get("/")
    assert "default-src 'self'" in response["Content-Security-Policy"]
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_healthz(client, db):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_supplier_cannot_set_own_commission(login, supplier_a):
    # No supplier view accepts commission fields; posting them to the profile has no effect.
    login(supplier_a.owner).post(
        reverse("suppliers:profile"), {"name": "Hof A", "pickup_same_as_address": "on", "commission_percent": "0"}
    )
    supplier_a.terms.refresh_from_db()
    assert supplier_a.terms.commission_percent is None


def test_unique_email_case_insensitive(db):
    from tests.conftest import make_user

    make_user("gross@hof.ch")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_user("GROSS@hof.ch")


def test_profile_change_is_logged_with_old_and_new_value(login, supplier_a):
    login(supplier_a.owner).post(
        reverse("suppliers:profile"),
        {"name": "Hof A", "pickup_same_as_address": "on", "city": "Liestal", "zip_code": "4410"},
    )
    event = AuditEvent.objects.get(action="org.updated", organization=supplier_a)
    assert event.changes["city"] == ["", "Liestal"]
