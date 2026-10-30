from django.http import HttpResponse

from .tenancy import resolve_tenant

EXEMPT_PATHS = ("/healthz", "/static/")


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(EXEMPT_PATHS):
            request.tenant = None
            return self.get_response(request)
        request.tenant = resolve_tenant(request.get_host())
        if request.tenant is None:
            return HttpResponse("Kein Marktplatz für diese Adresse eingerichtet.", status=404)
        return self.get_response(request)
