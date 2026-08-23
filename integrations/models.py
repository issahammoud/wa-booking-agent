from django.db import models

from tenants.models import Tenant


class CalendarConnection(models.Model):
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="calendar_connection"
    )
    provider = models.CharField(max_length=20, choices=Tenant.CalendarProvider.choices)
    external_calendar_id = models.CharField(max_length=255)
    access_token = models.BinaryField()
    refresh_token = models.BinaryField()
    token_expires_at = models.DateTimeField()
    scopes = models.JSONField(default=list, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"CalendarConnection({self.tenant_id}, {self.provider})"
