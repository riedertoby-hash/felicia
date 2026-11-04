from django.conf import settings
from django.core.cache import cache

from .models import Tenant

CACHE_SECONDS = 300


def resolve_tenant(host):
    """Find the tenant for a request host; fall back to the default tenant."""
    host = (host or "").split(":")[0].lower()
    key = f"tenant:{host}"
    tenant_id = cache.get(key)
    if tenant_id is not None:
        tenant = Tenant.objects.filter(pk=tenant_id, is_active=True).first()
        if tenant is not None:
            return tenant
    tenant = (
        Tenant.objects.filter(domain=host, is_active=True).first()
        or Tenant.objects.filter(slug=settings.DEFAULT_TENANT_SLUG, is_active=True).first()
    )
    if tenant is not None:
        cache.set(key, tenant.pk, CACHE_SECONDS)
    return tenant
