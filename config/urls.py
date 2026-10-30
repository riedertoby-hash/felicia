from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path

from apps.core import views as core_views

# Django admin uses the regular login (incl. 2FA) instead of its own form.
admin.site.login = login_required(admin.site.login)
admin.site.site_header = "Felicia – Systemverwaltung"

urlpatterns = [
    path("", core_views.home, name="home"),
    path("healthz", core_views.healthz, name="healthz"),
    path("konto/", include("allauth.urls")),
    path("konto/", include("apps.accounts.urls")),
    path("team/", include("apps.orgs.urls")),
    path("betreiber/", include("apps.operator.urls")),
    path("lieferant/", include("apps.suppliers.urls")),
    path("kunde/", include("apps.customers.urls")),
    path("system/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
