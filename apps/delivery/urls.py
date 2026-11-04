from django.urls import path

from . import views

app_name = "delivery"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("neu/", views.option_edit, name="option_new"),
    path("<int:pk>/", views.option_edit, name="option_edit"),
    path("<int:pk>/loeschen/", views.option_delete, name="option_delete"),
    path("<int:option_pk>/zone/neu/", views.zone_edit, name="zone_new"),
    path("<int:option_pk>/zone/<int:pk>/", views.zone_edit, name="zone_edit"),
    path("<int:option_pk>/zone/<int:pk>/loeschen/", views.zone_delete, name="zone_delete"),
]
