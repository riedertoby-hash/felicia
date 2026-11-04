"""Access tests: who may see and change what. These guard the most important promise of the platform."""

import pytest
from django.urls import reverse

from apps.orgs.models import Invitation, Membership

pytestmark = pytest.mark.django_db


# --- Tenant / organization isolation ---------------------------------------------------------------


def test_supplier_sees_only_own_profile(login, supplier_a, supplier_b):
    response = login(supplier_a.owner).get(reverse("suppliers:profile"))
    assert response.status_code == 200
    assert b"Hof A" in response.content
    assert b"Hof B" not in response.content


def test_cannot_change_role_in_other_org(login, supplier_a, supplier_b):
    target = Membership.objects.get(user=supplier_b.clerk)
    response = login(supplier_a.owner).post(
        reverse("orgs:change_role", args=[target.pk]), {f"m{target.pk}-role": target.role.pk}
    )
    assert response.status_code == 404


def test_cannot_remove_member_of_other_org(login, supplier_a, supplier_b):
    target = Membership.objects.get(user=supplier_b.clerk)
    response = login(supplier_a.owner).post(reverse("orgs:remove_member", args=[target.pk]))
    assert response.status_code == 404
    assert Membership.objects.filter(pk=target.pk).exists()


def test_cannot_revoke_invitation_of_other_org(login, supplier_a, supplier_b):
    invitation, _ = Invitation.issue(
        organization=supplier_b,
        email="x@y.ch",
        role=Membership.objects.get(user=supplier_b.clerk).role,
        invited_by=supplier_b.owner,
    )
    response = login(supplier_a.owner).post(reverse("orgs:revoke_invitation", args=[invitation.pk]))
    assert response.status_code == 404


def test_cannot_switch_to_foreign_org(login, supplier_a, supplier_b):
    client = login(supplier_a.owner)
    client.post(reverse("orgs:switch"), {"organization": supplier_b.pk})
    response = client.get(reverse("suppliers:profile"))
    assert b"Hof A" in response.content and b"Hof B" not in response.content


def test_team_page_lists_only_own_members(login, supplier_a, supplier_b):
    response = login(supplier_a.owner).get(reverse("orgs:team"))
    assert b"clerk@hof-a.ch" in response.content
    assert b"hof-b.ch" not in response.content


# --- Areas by organization kind --------------------------------------------------------------------


@pytest.mark.parametrize("url", ["operator:dashboard", "operator:suppliers", "operator:settings", "operator:audit"])
def test_supplier_cannot_open_operator_area(login, supplier_a, operator, url):
    assert login(supplier_a.owner).get(reverse(url)).status_code == 403


def test_customer_cannot_open_supplier_area(login, customer):
    assert login(customer.owner).get(reverse("suppliers:dashboard")).status_code == 403


def test_supplier_cannot_open_customer_area(login, supplier_a):
    assert login(supplier_a.owner).get(reverse("customers:dashboard")).status_code == 403


def test_anonymous_is_sent_to_login(client, tenant):
    response = client.get(reverse("suppliers:dashboard"))
    assert response.status_code == 302 and "/konto/login/" in response["Location"]


# --- Roles inside a supplier -----------------------------------------------------------------------


def test_clerk_cannot_edit_profile(login, supplier_a):
    client = login(supplier_a.clerk)
    assert client.get(reverse("suppliers:profile")).status_code == 200  # may look
    client.post(reverse("suppliers:profile"), {"name": "Gehackt", "pickup_same_as_address": "on"})
    supplier_a.refresh_from_db()
    assert supplier_a.name == "Hof A"


@pytest.mark.parametrize("role", ["admin", "clerk", "readonly"])
def test_only_owner_manages_bank(login, supplier_a, role):
    assert login(getattr(supplier_a, role)).get(reverse("suppliers:bank")).status_code == 403


@pytest.mark.parametrize("role", ["admin", "clerk", "readonly"])
def test_only_owner_manages_team(login, supplier_a, role):
    assert login(getattr(supplier_a, role)).get(reverse("orgs:team")).status_code == 403


def test_admin_can_edit_profile(login, supplier_a):
    response = login(supplier_a.admin).post(
        reverse("suppliers:profile"),
        {"name": "Hof A Neu", "pickup_same_as_address": "on", "zip_code": "4410", "city": "Liestal"},
    )
    assert response.status_code == 302
    supplier_a.refresh_from_db()
    assert supplier_a.name == "Hof A Neu"


def test_buyer_cannot_manage_addresses(login, customer):
    assert login(customer.buyer).get(reverse("customers:addresses")).status_code == 403


def test_customer_address_isolation(login, customer, tenant):
    from apps.customers.models import Address
    from apps.orgs.services import create_organization
    from tests.conftest import make_user

    other_owner = make_user("chef@baeren.ch")
    other = create_organization(tenant=tenant, kind="customer", name="Bären", owner=other_owner)
    address = Address.objects.create(
        organization=other, label="Küche", recipient="Bären", street="Weg 1", zip_code="4000", city="Basel"
    )
    client = login(customer.owner)
    assert client.get(reverse("customers:address_edit", args=[address.pk])).status_code == 404
    assert client.post(reverse("customers:address_delete", args=[address.pk])).status_code == 404
    assert Address.objects.filter(pk=address.pk).exists()


# --- Operator roles --------------------------------------------------------------------------------


def test_operator_staff_can_view_but_not_manage(login, operator, supplier_a):
    client = login(operator.staff)
    assert client.get(reverse("operator:suppliers")).status_code == 200
    assert client.post(reverse("operator:set_status", args=[supplier_a.pk]), {"action": "block"}).status_code == 403
    assert client.get(reverse("operator:settings")).status_code == 403
    assert client.get(reverse("operator:audit")).status_code == 403


def test_operator_staff_cannot_change_terms(login, operator, supplier_a):
    client = login(operator.staff)
    client.post(reverse("operator:supplier", args=[supplier_a.pk]), {"commission_percent": "1"})
    supplier_a.terms.refresh_from_db()
    assert supplier_a.terms.commission_percent is None


# --- Blocking ------------------------------------------------------------------------------------


def test_blocked_supplier_loses_access(login, operator, supplier_a):
    login(operator.admin).post(reverse("operator:set_status", args=[supplier_a.pk]), {"action": "block"})
    supplier_a.refresh_from_db()
    assert supplier_a.status == "blocked"
    client = login(supplier_a.owner)
    assert client.get(reverse("suppliers:dashboard")).status_code == 403
    assert "Noch kein Zugang" in client.get("/").content.decode()
