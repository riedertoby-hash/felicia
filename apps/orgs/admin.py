from django.contrib import admin

from .models import Invitation, Membership, Organization, Role


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "status", "tenant", "created_at")
    list_filter = ("kind", "status", "tenant")
    search_fields = ("name",)
    inlines = [MembershipInline]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "kind", "tenant", "is_owner", "sort")
    list_filter = ("kind",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "role", "created_at", "expires_at", "accepted_at", "revoked_at")
    exclude = ("token_hash",)
