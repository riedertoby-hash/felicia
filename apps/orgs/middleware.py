from .models import Membership

SESSION_KEY = "active_org_id"


class OrganizationMiddleware:
    """Attaches the user's active membership/organization for this tenant to the request.
    Views must take the organization from here, never from URL or form input."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.membership = None
        request.org = None
        request.memberships = []
        tenant = getattr(request, "tenant", None)
        if tenant is not None and request.user.is_authenticated:
            memberships = list(
                Membership.objects.filter(user=request.user, is_active=True, organization__tenant=tenant)
                .exclude(organization__status="blocked")
                .select_related("organization", "role")
                .order_by("organization__kind", "organization__name")
            )
            request.memberships = memberships
            active_id = request.session.get(SESSION_KEY)
            chosen = next((m for m in memberships if m.organization_id == active_id), None)
            if chosen is None and memberships:
                chosen = memberships[0]
            if chosen is not None:
                request.membership = chosen
                request.org = chosen.organization
        return self.get_response(request)
