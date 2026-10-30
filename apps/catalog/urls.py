from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("", views.product_list, name="list"),
    path("neu/", views.product_edit, name="new"),
    path("<int:pk>/", views.product_edit, name="edit"),
    path("<int:pk>/aktiv/", views.product_toggle, name="toggle"),
    path("<int:pk>/loeschen/", views.product_delete, name="delete"),
    path("import/", views.csv_upload, name="csv"),
    path("import/bestaetigen/", views.csv_confirm, name="csv_confirm"),
    path("import/vorlage.csv", views.csv_template, name="csv_template"),
    path("export.csv", views.csv_export, name="csv_export"),
]
