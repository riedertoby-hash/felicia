from django.urls import path

from . import operator_views as views

app_name = "catalog_admin"
urlpatterns = [
    path("", views.taxonomy, name="taxonomy"),
    path("kategorie/neu/", views.category_edit, name="category_new"),
    path("kategorie/<int:pk>/", views.category_edit, name="category_edit"),
    path("kategorie/<int:pk>/loeschen/", views.category_delete, name="category_delete"),
    path("label/neu/", views.label_add, name="label_add"),
    path("label/<int:pk>/loeschen/", views.label_delete, name="label_delete"),
]
