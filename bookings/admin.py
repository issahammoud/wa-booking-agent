from django.contrib import admin

from bookings.models import BlockedDate, Booking, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "duration_minutes", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("name",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("tenant", "end_user", "service", "scheduled_start", "status")
    list_filter = ("tenant", "status")
    search_fields = ("end_user__phone_number", "external_event_id")


@admin.register(BlockedDate)
class BlockedDateAdmin(admin.ModelAdmin):
    list_display = ("tenant", "date", "reason")
    list_filter = ("tenant",)
    search_fields = ("reason",)
