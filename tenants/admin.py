from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from tenants.models import StaffUser, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("business_name", "vertical", "subscription_tier", "is_active", "created_at")
    list_filter = ("vertical", "subscription_tier", "is_active")
    search_fields = ("business_name", "waba_id", "phone_number_id")


@admin.register(StaffUser)
class StaffUserAdmin(UserAdmin):
    list_display = ("username", "email", "tenant", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email")
    fieldsets = UserAdmin.fieldsets + (("Tenant", {"fields": ("tenant", "role")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Tenant", {"fields": ("tenant", "role")}),)
