from django.contrib import admin

from .models import Category, Label, Product, Variant


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "supplier", "category", "is_active")
    list_filter = ("is_active", "temperature")
    search_fields = ("name",)
    inlines = [VariantInline]


admin.site.register(Category)
admin.site.register(Label)
