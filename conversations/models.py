from django.conf import settings
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


class Conversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        AWAITING_USER = "awaiting_user", "Awaiting user"
        ESCALATED = "escalated", "Escalated"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="conversations")
    end_user = models.ForeignKey(EndUser, on_delete=models.CASCADE, related_name="conversations")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    # e.g. {"intent": "book_appointment", "slots": {...}}
    pending_intent_state = models.JSONField(default=dict, blank=True)
    # Bounded conversation memory (integrations/agent/memory.py) - a short
    # running summary of messages that have fallen outside the agent's
    # verbatim history window, and the id of the last message folded into
    # it, so re-summarization only processes what's newly aged out.
    context_summary = models.TextField(blank=True)
    context_summary_through_message_id = models.PositiveBigIntegerField(null=True, blank=True)
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_conversations",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversation({self.end_user_id}, {self.status})"


class Message(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    class MessageType(models.TextChoices):
        TEXT = "text", "Text"
        AUDIO = "audio", "Audio"
        IMAGE = "image", "Image"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    message_type = models.CharField(max_length=10, choices=MessageType.choices)
    content = models.TextField(blank=True)
    media_reference = models.CharField(max_length=255, blank=True)
    whatsapp_message_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="msg_conv_created_idx"),
        ]

    def __str__(self):
        return f"Message({self.direction}, {self.message_type})"
