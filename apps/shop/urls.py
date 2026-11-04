from django.urls import path

from . import views

app_name = "shop"
urlpatterns = [
    path("", views.index, name="index"),
    path("artikel/<int:pk>/", views.product_detail, name="product"),
    path("lieferanten/", views.suppliers, name="suppliers"),
    path("lieferanten/<int:pk>/", views.supplier_detail, name="supplier"),
]
