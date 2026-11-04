from django.contrib import admin

from .models import MarketplaceSettings, SupplierTerms

admin.site.register(MarketplaceSettings)
admin.site.register(SupplierTerms)
