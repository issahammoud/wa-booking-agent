from django.core.exceptions import ValidationError
from django.db import models

from conversations.models import Conversation, EndUser
from tenants.models import Tenant


class Service(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=255)
    duration_minutes = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No show"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bookings")
    end_user = models.ForeignKey(EndUser, on_delete=models.CASCADE, related_name="bookings")
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings"
    )
    conversation = models.ForeignKey(
        Conversation, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings"
    )
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMED)
    external_event_id = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "scheduled_start"],
                condition=models.Q(status="confirmed"),
                name="unique_confirmed_tenant_slot",
            )
        ]

    def __str__(self):
        return f"Booking({self.tenant_id}, {self.scheduled_start})"

    def clean(self):
        if self.scheduled_end <= self.scheduled_start:
            raise ValidationError("scheduled_end must be after scheduled_start.")


class BlockedDate(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="blocked_dates")
    date = models.DateField()
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "date"], name="unique_tenant_blocked_date")
        ]

    def __str__(self):
        return f"BlockedDate({self.tenant_id}, {self.date})"
