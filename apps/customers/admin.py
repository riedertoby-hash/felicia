from django.contrib import admin

from .models import Address, CustomerProfile

admin.site.register(CustomerProfile)
admin.site.register(Address)
