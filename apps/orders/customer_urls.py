from django.urls import path

from . import customer_views as views

app_name = "orders"
urlpatterns = [
    path("warenkorb/", views.cart, name="cart"),
    path("warenkorb/hinzufuegen/<int:variant_id>/", views.add, name="add"),
    path("warenkorb/<int:pk>/menge/", views.update_item, name="update_item"),
    path("warenkorb/<int:pk>/entfernen/", views.remove_item, name="remove_item"),
    path("warenkorb/bestellen/", views.checkout, name="checkout"),
    path("bestellungen/", views.order_list, name="list"),
    path("bestellungen/<int:pk>/", views.order_detail, name="detail"),
    path("bestellungen/<int:pk>/nochmals/", views.reorder, name="reorder"),
    path("bestellungen/<int:pk>/lieferschein.pdf", views.delivery_note, name="delivery_note"),
]
