from django.urls import path

from . import keys, views

app_name = "api"
urlpatterns = [
    path("v1/orders", views.orders, name="orders"),
    path("v1/orders/<str:number>", views.order_detail, name="order"),
    path("v1/orders/<str:number>/status", views.order_status, name="order_status"),
    path("v1/products", views.products, name="products"),
    path("v1/variants/<str:sku>", views.variant_update, name="variant"),
    path("v1/invoices", views.invoices, name="invoices"),
    path("schluessel/", keys.key_list, name="keys"),
    path("schluessel/<int:pk>/widerrufen/", keys.revoke, name="revoke"),
]
