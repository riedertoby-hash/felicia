from django.contrib import admin

from .models import SupplierProfile


@admin.register(SupplierProfile)
class SupplierProfileAdmin(admin.ModelAdmin):
    list_display = ("organization", "city", "contact_email")
    exclude = ("iban",)
    readonly_fields = ("iban_masked",)
