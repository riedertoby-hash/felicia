from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache


def home(request):
    if not request.user.is_authenticated:
        return render(request, "core/landing.html")
    org = getattr(request, "org", None)
    if org is None:
        return render(request, "core/no_org.html")
    return redirect(org.dashboard_url)


@never_cache
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "db": "down"}, status=503)
    return JsonResponse({"status": "ok"})
