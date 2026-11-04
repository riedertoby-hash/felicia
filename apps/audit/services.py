from .models import AuditEvent


def client_ip(request):
    if request is None:
        return None
    # Behind the reverse proxy, the proxy sets X-Real-IP; never trust a client-sent header otherwise.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def log(action, *, request=None, actor=None, organization=None, tenant=None, target=None, changes=None):
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user
    if tenant is None:
        tenant = getattr(organization, "tenant", None) or getattr(request, "tenant", None)
    return AuditEvent.objects.create(
        tenant=tenant,
        organization=organization,
        actor=actor,
        actor_label=getattr(actor, "email", "") or "",
        action=action,
        target_type=target._meta.model_name if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        target_label=str(target)[:254] if target is not None else "",
        changes=changes or {},
        ip_address=client_ip(request),
    )


def diff(before, after, fields, masked=()):
    """Return {field: [old, new]} for changed fields; masked fields show only that they changed."""
    result = {}
    for name in fields:
        old, new = before.get(name), after.get(name)
        if old != new:
            result[name] = ["•••", "•••"] if name in masked else [_plain(old), _plain(new)]
    return result


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def snapshot(instance, fields):
    return {name: getattr(instance, name) for name in fields}
