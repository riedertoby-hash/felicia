import pytest
from django.core import mail
from django.urls import reverse

from apps.orgs.models import Membership, Organization


def _signup(client, **data):
    payload = {
        "account_type": "supplier",
        "organization_name": "Hof Sonnenberg",
        "first_name": "Anna",
        "last_name": "Muster",
        "email": "anna@sonnenberg.ch",
        "password1": "Kartoffel-Hof-2026!",
        "password2": "Kartoffel-Hof-2026!",
        "accept_terms": "on",
    }
    payload.update(data)
    return client.post(reverse("account_signup"), payload)


@pytest.mark.django_db
def test_supplier_signup_creates_pending_org_with_owner(client, tenant):
    response = _signup(client)
    assert response.status_code == 302
    org = Organization.objects.get(name="Hof Sonnenberg")
    assert org.kind == "supplier" and org.status == "pending"
    membership = Membership.objects.get(organization=org)
    assert membership.role.key == "supplier_owner"
    assert org.supplier_profile.contact_email == "anna@sonnenberg.ch"
    assert org.terms is not None
    assert len(mail.outbox) == 1  # email confirmation


@pytest.mark.django_db
def test_business_customer_signup_is_active(client, tenant):
    _signup(client, account_type="customer_business", organization_name="Restaurant Krone")
    org = Organization.objects.get(name="Restaurant Krone")
    assert org.kind == "customer" and org.status == "active"
    assert org.customer_profile.customer_type == "business"


@pytest.mark.django_db
def test_supplier_signup_requires_org_name(client, tenant):
    response = _signup(client, organization_name="")
    assert response.status_code == 200
    assert not Organization.objects.exists()


@pytest.mark.django_db
def test_short_password_rejected(client, tenant):
    response = _signup(client, password1="kurz", password2="kurz")
    assert response.status_code == 200
    assert not Organization.objects.exists()


@pytest.mark.django_db
def test_no_approval_needed_when_disabled(client, tenant, mp_settings):
    mp_settings.supplier_approval_required = False
    mp_settings.save()
    _signup(client)
    assert Organization.objects.get(name="Hof Sonnenberg").status == "active"
