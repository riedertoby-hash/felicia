from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.orgs.models import Invitation, Membership, Role

pytestmark = pytest.mark.django_db


def _invite(client, email="neu@hof-a.ch", role_key="supplier_clerk"):
    role = Role.objects.get(tenant=None, key=role_key)
    client.post(reverse("orgs:invite"), {"email": email, "role": role.pk})
    body = mail.outbox[-1].body
    return body.split("/team/einladung/")[1].split("/")[0]


def test_invite_new_person_and_signup(client, login, supplier_a):
    token = _invite(login(supplier_a.owner))
    client.logout()
    response = client.post(
        reverse("orgs:accept", args=[token]),
        {
            "first_name": "Neu",
            "last_name": "Person",
            "password1": "Sellerie-Kiste-2026!",
            "password2": "Sellerie-Kiste-2026!",
            "accept_terms": "on",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(email="neu@hof-a.ch")
    membership = Membership.objects.get(user=user)
    assert membership.organization == supplier_a and membership.role.key == "supplier_clerk"
    assert AuditEvent.objects.filter(action="invite.accepted", organization=supplier_a).exists()
    # Token cannot be used twice
    client.logout()
    assert client.get(reverse("orgs:accept", args=[token])).status_code == 404


def test_expired_invitation_is_rejected(client, login, supplier_a):
    token = _invite(login(supplier_a.owner))
    Invitation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    client.logout()
    assert client.get(reverse("orgs:accept", args=[token])).status_code == 404


def test_invitation_for_other_email_cannot_be_taken(client, login, supplier_a, supplier_b):
    token = _invite(login(supplier_a.owner), email="jemand@anders.ch")
    client.logout()
    login(supplier_b.owner).post(reverse("orgs:accept", args=[token]))
    assert not Membership.objects.filter(user=supplier_b.owner, organization=supplier_a).exists()


def test_existing_user_must_log_in(client, login, supplier_a, supplier_b):
    token = _invite(login(supplier_a.owner), email=supplier_b.owner.email)
    client.logout()
    response = client.get(reverse("orgs:accept", args=[token]))
    assert "Anmelden" in response.content.decode()
    client.force_login(supplier_b.owner)
    client.post(reverse("orgs:accept", args=[token]))
    assert Membership.objects.filter(user=supplier_b.owner, organization=supplier_a).exists()


def test_token_is_stored_hashed(login, supplier_a):
    token = _invite(login(supplier_a.owner))
    assert not Invitation.objects.filter(token_hash=token).exists()
    assert Invitation.objects.filter(token_hash=Invitation.hash_token(token)).exists()


def test_cannot_demote_or_remove_last_owner(login, supplier_a):
    second_owner_role = Role.objects.get(tenant=None, key="supplier_owner")
    other = Membership.objects.get(user=supplier_a.admin)
    client = login(supplier_a.owner)
    # promote admin to owner, then the admin demotes the original owner: allowed (one owner left)
    client.post(reverse("orgs:change_role", args=[other.pk]), {f"m{other.pk}-role": second_owner_role.pk})
    other.refresh_from_db()
    assert other.role.is_owner
    owner_membership = Membership.objects.get(user=supplier_a.owner)
    clerk_role = Role.objects.get(tenant=None, key="supplier_clerk")
    login(supplier_a.admin).post(
        reverse("orgs:change_role", args=[owner_membership.pk]), {f"m{owner_membership.pk}-role": clerk_role.pk}
    )
    owner_membership.refresh_from_db()
    assert owner_membership.role == clerk_role
    # now supplier_a.admin is the only owner; nobody can demote them (they can't edit themselves)
    response = login(supplier_a.admin).post(reverse("orgs:remove_member", args=[other.pk]))
    assert response.status_code == 302
    assert Membership.objects.filter(pk=other.pk).exists()


def test_role_from_other_kind_is_rejected(login, supplier_a):
    role = Role.objects.get(tenant=None, key="operator_admin")
    target = Membership.objects.get(user=supplier_a.clerk)
    login(supplier_a.owner).post(reverse("orgs:change_role", args=[target.pk]), {f"m{target.pk}-role": role.pk})
    target.refresh_from_db()
    assert target.role.key == "supplier_clerk"
