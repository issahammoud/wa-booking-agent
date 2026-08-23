from django.contrib.auth.models import AbstractUser
from django.db import models


class Tenant(models.Model):
    class Vertical(models.TextChoices):
        DOCTOR = "doctor", "Doctor"
        LAWYER = "lawyer", "Lawyer"
        OTHER = "other", "Other"

    class CalendarProvider(models.TextChoices):
        INTERNAL = "internal", "Internal"
        GOOGLE = "google", "Google"
        OUTLOOK = "outlook", "Outlook"

    class SubscriptionTier(models.TextChoices):
        TRIAL = "trial", "Trial"
        BASIC = "basic", "Basic"
        PRO = "pro", "Pro"

    business_name = models.CharField(max_length=255)
    vertical = models.CharField(max_length=20, choices=Vertical.choices)
    timezone = models.CharField(max_length=63, default="Asia/Beirut")

    # unique=True already creates the index the ticket asks for.
    waba_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    phone_number_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    whatsapp_access_token = models.BinaryField(null=True, blank=True)
    whatsapp_connected_at = models.DateTimeField(null=True, blank=True)

    calendar_provider = models.CharField(
        max_length=20, choices=CalendarProvider.choices, default=CalendarProvider.INTERNAL
    )
    working_hours = models.JSONField(default=dict, blank=True)
    default_slot_duration_minutes = models.PositiveIntegerField(default=30)
    booking_buffer_minutes = models.PositiveIntegerField(default=0)

    subscription_tier = models.CharField(
        max_length=20, choices=SubscriptionTier.choices, default=SubscriptionTier.TRIAL
    )
    monthly_conversation_quota = models.PositiveIntegerField(default=100)

    system_prompt_overrides = models.JSONField(default=dict, blank=True)
    language_defaults = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.business_name


class StaffUser(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        STAFF = "staff", "Staff"
        PLATFORM_ADMIN = "platform_admin", "Platform Admin"

    # Nullable: platform admins aren't scoped to any single tenant.
    tenant = models.ForeignKey(
        Tenant, null=True, blank=True, on_delete=models.CASCADE, related_name="staff_users"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
