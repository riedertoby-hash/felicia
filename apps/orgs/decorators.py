from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def org_required(perm=None, kind=None):
    """Require an active organization (optionally of a kind) and a permission from the user's role."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            membership = request.membership
            if membership is None:
                raise PermissionDenied("Kein Zugang zu einer Organisation.")
            if kind is not None and request.org.kind != kind:
                raise PermissionDenied("Diese Seite gehört zu einem anderen Bereich.")
            if perm is not None and not membership.has_perm(perm):
                raise PermissionDenied("Ihre Rolle erlaubt diese Aktion nicht.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
