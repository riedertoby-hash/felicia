from django.urls import path

from . import supplier_views as views

app_name = "supplier_orders"
urlpatterns = [
    path("", views.order_list, name="list"),
    path("alle-bestaetigen/", views.confirm_all, name="confirm_all"),
    path("export.csv", views.export_csv, name="export"),
    path("tag/", views.day, name="today"),
    path("tag/<str:day>/", views.day, name="day"),
    path("tag/<str:day>/kommissionierliste.pdf", views.picking_pdf, name="picking_pdf"),
    path("tag/<str:day>/lieferscheine.pdf", views.delivery_notes_pdf, name="delivery_notes_pdf"),
    path("<int:pk>/", views.order_detail, name="detail"),
    path("<int:pk>/status/", views.set_status, name="set_status"),
    path("<int:pk>/lieferschein.pdf", views.delivery_note_pdf, name="delivery_note"),
]
