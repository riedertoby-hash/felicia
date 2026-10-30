from django.urls import path

from . import views

app_name = "operator"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("lieferanten/", views.suppliers, name="suppliers"),
    path("lieferanten/<int:pk>/", views.supplier_detail, name="supplier"),
    path("organisation/<int:pk>/status/", views.set_status, name="set_status"),
    path("kunden/", views.customers, name="customers"),
    path("einstellungen/", views.settings_view, name="settings"),
    path("protokoll/", views.audit, name="audit"),
]
