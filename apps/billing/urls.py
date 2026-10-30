from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [
    path("lieferant/rechnungen/", views.supplier_invoices, name="supplier_invoices"),
    path("lieferant/rechnungen/einstellungen/", views.supplier_settings, name="supplier_settings"),
    path("lieferant/rechnungen/abweichung/<int:pk>/loeschen/", views.delete_terms, name="delete_terms"),
    path("lieferant/rechnungen/kunde/<int:customer_id>/erstellen/", views.create_invoice, name="create_invoice"),
    path("lieferant/rechnungen/<int:pk>/", views.supplier_invoice, name="supplier_invoice"),
    path("lieferant/kunden/", views.supplier_customers, name="supplier_customers"),
    path("kunde/rechnungen/", views.customer_invoices, name="customer_invoices"),
    path("kunde/rechnungen/<int:pk>/", views.customer_invoice, name="customer_invoice"),
    path("betreiber/provisionen/", views.operator_invoices, name="operator_invoices"),
    path("betreiber/provisionen/erstellen/", views.operator_run, name="operator_run"),
    path("betreiber/provisionen/<int:pk>/", views.operator_invoice, name="operator_invoice"),
    path("betreiber/rechnungsdaten/", views.operator_issuer, name="operator_issuer"),
    path("rechnung/<int:pk>.pdf", views.invoice_pdf_view, name="pdf"),
    path("rechnung/<int:pk>/bezahlt/", views.invoice_paid, name="paid"),
    path("rechnung/<int:pk>/stornieren/", views.invoice_cancel, name="cancel"),
]
