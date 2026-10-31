from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log

from .models import Invitation, Membership, Organization, Role
from .signals import organization_created


def default_owner_role(kind):
    return Role.objects.get(tenant__isnull=True, kind=kind, is_owner=True)


@transaction.atomic
def create_organization(*, tenant, kind, name, owner, request=None, **options):
    from apps.operator.models import MarketplaceSettings

    status = Organization.Status.ACTIVE
    if kind == Organization.Kind.SUPPLIER and MarketplaceSettings.for_tenant(tenant).supplier_approval_required:
        status = Organization.Status.PENDING
    org = Organization.objects.create(tenant=tenant, kind=kind, name=name, status=status)
    Membership.objects.create(user=owner, organization=org, role=default_owner_role(kind))
    organization_created.send(sender=Organization, organization=org, owner=owner, options=options)
    log("org.created", request=request, actor=owner, organization=org, target=org, changes={"kind": kind})
    return org


@transaction.atomic
def create_organization_without_owner(*, tenant, kind, name, status, request=None, **options):
    """For imports: the organization exists before its people; the owner joins via invitation."""
    org = Organization.objects.create(tenant=tenant, kind=kind, name=name, status=status)
    organization_created.send(sender=Organization, organization=org, owner=None, options=options)
    log("org.created", request=request, organization=org, target=org, changes={"kind": kind, "import": True})
    return org


def _owners(org):
    return Membership.objects.filter(organization=org, is_active=True, role__is_owner=True)


@transaction.atomic
def change_role(*, membership, role, request):
    if role.kind != membership.organization.kind:
        raise ValidationError("Rolle passt nicht zur Organisation.")
    if membership.user_id == request.user.id:
        raise PermissionDenied("Die eigene Rolle kann nicht geändert werden.")
    Membership.objects.select_for_update().filter(organization=membership.organization)
    if membership.role.is_owner and not role.is_owner and _owners(membership.organization).count() <= 1:
        raise ValidationError("Es braucht mindestens einen Inhaber.")
    old = membership.role
    membership.role = role
    membership.save(update_fields=["role"])
    log(
        "member.role_changed",
        request=request,
        organization=membership.organization,
        target=membership.user,
        changes={"role": [old.name, role.name]},
    )


@transaction.atomic
def remove_member(*, membership, request):
    if membership.user_id == request.user.id:
        raise PermissionDenied("Sie können sich nicht selbst entfernen.")
    if membership.role.is_owner and _owners(membership.organization).count() <= 1:
        raise ValidationError("Es braucht mindestens einen Inhaber.")
    user, org = membership.user, membership.organization
    membership.delete()
    log("member.removed", request=request, organization=org, target=user)


def invite(*, organization, email, role, request):
    email = email.lower()
    if role.kind != organization.kind:
        raise ValidationError("Rolle passt nicht zur Organisation.")
    if Membership.objects.filter(organization=organization, user__email=email).exists():
        raise ValidationError("Diese Person ist bereits Mitglied.")
    Invitation.objects.open().filter(organization=organization, email=email).update(revoked_at=timezone.now())
    invitation, token = Invitation.issue(organization=organization, email=email, role=role, invited_by=request.user)
    log(
        "invite.sent",
        request=request,
        organization=organization,
        target=invitation,
        changes={"email": email, "role": role.name},
    )
    return invitation, token


@transaction.atomic
def accept_invitation(*, invitation, user, request):
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.is_open:
        raise ValidationError("Diese Einladung ist nicht mehr gültig.")
    if user.email.lower() != invitation.email:
        raise PermissionDenied("Diese Einladung gilt für eine andere E-Mail-Adresse.")
    membership, created = Membership.objects.get_or_create(
        user=user, organization=invitation.organization, defaults={"role": invitation.role}
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    log(
        "invite.accepted",
        request=request,
        actor=user,
        organization=invitation.organization,
        target=user,
        changes={"role": invitation.role.name},
    )
    return membership


def revoke_invitation(*, invitation, request):
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    log(
        "invite.revoked",
        request=request,
        organization=invitation.organization,
        target=invitation,
        changes={"email": invitation.email},
    )
