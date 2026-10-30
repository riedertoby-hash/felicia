import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.operator.models import MarketplaceSettings
from apps.orgs.models import Membership, Role
from apps.orgs.services import create_organization

PASSWORD = "Rueebli-Acker-2026!"


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.PWNED_PASSWORDS_CHECK = False
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.ACCOUNT_RATE_LIMITS = False


@pytest.fixture
def tenant(db):
    t = Tenant.objects.create(slug="feldzutisch", name="Feld zu Tisch")
    MarketplaceSettings.objects.create(tenant=t, mfa_required_roles=[])
    return t


@pytest.fixture
def mp_settings(tenant):
    return MarketplaceSettings.for_tenant(tenant)


def make_user(email, **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name="Test", last_name=email[:3], **extra)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def add_member(org, email, role_key):
    user = make_user(email)
    Membership.objects.create(user=user, organization=org, role=Role.objects.get(tenant=None, key=role_key))
    return user


def give_mfa(user):
    Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={"secret": "x"})


@pytest.fixture
def operator(tenant):
    admin = make_user("admin@betreiber.ch")
    org = create_organization(tenant=tenant, kind="operator", name="Feld zu Tisch", owner=admin)
    org.admin = admin
    org.staff = add_member(org, "staff@betreiber.ch", "operator_staff")
    return org


@pytest.fixture
def supplier_a(tenant):
    owner = make_user("owner@hof-a.ch")
    org = create_organization(tenant=tenant, kind="supplier", name="Hof A", owner=owner)
    org.status = "active"
    org.save()
    org.owner = owner
    org.admin = add_member(org, "admin@hof-a.ch", "supplier_admin")
    org.clerk = add_member(org, "clerk@hof-a.ch", "supplier_clerk")
    org.readonly = add_member(org, "buchhaltung@hof-a.ch", "supplier_readonly")
    return org


@pytest.fixture
def supplier_b(tenant):
    owner = make_user("owner@hof-b.ch")
    org = create_organization(tenant=tenant, kind="supplier", name="Hof B", owner=owner)
    org.status = "active"
    org.save()
    org.owner = owner
    org.clerk = add_member(org, "clerk@hof-b.ch", "supplier_clerk")
    return org


@pytest.fixture
def customer(tenant):
    owner = make_user("chef@restaurant.ch")
    org = create_organization(
        tenant=tenant, kind="customer", name="Restaurant Linde", owner=owner, customer_type="business"
    )
    org.owner = owner
    org.buyer = add_member(org, "koch@restaurant.ch", "customer_buyer")
    return org


@pytest.fixture
def login(client):
    def _login(user):
        client.force_login(user)
        return client

    return _login
