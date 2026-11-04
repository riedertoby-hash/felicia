from django.urls import path

from . import views

app_name = "customers"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("profil/", views.profile, name="profile"),
    path("adressen/", views.addresses, name="addresses"),
    path("adressen/neu/", views.address_edit, name="address_new"),
    path("adressen/<int:pk>/", views.address_edit, name="address_edit"),
    path("adressen/<int:pk>/loeschen/", views.address_delete, name="address_delete"),
]
