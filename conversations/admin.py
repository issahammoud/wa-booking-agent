from django.contrib import admin

from conversations.models import Conversation, EndUser, Message


@admin.register(EndUser)
class EndUserAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "display_name", "tenant", "created_at")
    list_filter = ("tenant",)
    search_fields = ("phone_number", "display_name")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("end_user", "tenant", "status", "assigned_staff", "last_message_at")
    list_filter = ("tenant", "status")
    search_fields = ("end_user__phone_number",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "direction", "message_type", "created_at")
    list_filter = ("direction", "message_type")
    search_fields = ("whatsapp_message_id", "content")
