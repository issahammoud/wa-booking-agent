from django.db import models

from tenants.models import Tenant


class EndUser(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="end_users")
    phone_number = models.CharField(max_length=32)  # E.164 format
    display_name = models.CharField(max_length=255, blank=True)
    preferred_language = models.CharField(max_length=8, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "phone_number"], name="unique_tenant_phone_number"
            )
        ]

    def __str__(self):
        return f"{self.phone_number} ({self.tenant_id})"
