import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TenantModel


class Organization(TenantModel):
    """Operator, supplier or customer company. All business data hangs off an organization."""

    class Kind(models.TextChoices):
        OPERATOR = "operator", "Betreiber"
        SUPPLIER = "supplier", "Lieferant"
        CUSTOMER = "customer", "Kunde"

    class Status(models.TextChoices):
        PENDING = "pending", "Wartet auf Freischaltung"
        ACTIVE = "active", "Aktiv"
        BLOCKED = "blocked", "Gesperrt"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField("Name", max_length=160)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    status_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Organisation"
        verbose_name_plural = "Organisationen"
        indexes = [models.Index(fields=["tenant", "kind", "status"])]

    def __str__(self):
        return self.name

    @property
    def dashboard_url(self):
        return reverse(
            {"operator": "operator:dashboard", "supplier": "suppliers:dashboard", "customer": "shop:index"}[self.kind]
        )

    @property
    def is_blocked(self):
        return self.status == self.Status.BLOCKED


class RoleQuerySet(models.QuerySet):
    def for_org(self, org):
        return self.filter(kind=org.kind).filter(models.Q(tenant__isnull=True) | models.Q(tenant=org.tenant))


class Role(models.Model):
    """Named bundle of permission keys. System roles have no tenant; a tenant may add its own."""

    tenant = models.ForeignKey("core.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    key = models.SlugField(max_length=64)
    kind = models.CharField(max_length=16, choices=Organization.Kind.choices)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    permissions = models.JSONField(default=list)
    is_owner = models.BooleanField(default=False, help_text="Inhaber-Rolle: mindestens einer pro Organisation")
    sort = models.PositiveSmallIntegerField(default=100)

    objects = RoleQuerySet.as_manager()

    class Meta:
        ordering = ["kind", "sort"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="role_unique_key_per_tenant", nulls_distinct=False)
        ]
        verbose_name = "Rolle"
        verbose_name_plural = "Rollen"

    def __str__(self):
        return self.name


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "organization"], name="membership_unique")]
        verbose_name = "Mitgliedschaft"
        verbose_name_plural = "Mitgliedschaften"

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"

    def has_perm(self, perm):
        return self.is_active and perm in self.role.permissions


class InvitationQuerySet(models.QuerySet):
    def open(self):
        return self.filter(accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())


class Invitation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Einladung"
        verbose_name_plural = "Einladungen"

    def __str__(self):
        return f"{self.email} → {self.organization}"

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def issue(cls, *, organization, email, role, invited_by):
        token = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            organization=organization,
            email=email.lower(),
            role=role,
            invited_by=invited_by,
            token_hash=cls.hash_token(token),
            expires_at=timezone.now() + timedelta(days=settings.INVITATION_VALID_DAYS),
        )
        return invitation, token

    @classmethod
    def find_open(cls, token):
        return (
            cls.objects.open().select_related("organization", "role").filter(token_hash=cls.hash_token(token)).first()
        )

    @property
    def is_open(self):
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > timezone.now()
