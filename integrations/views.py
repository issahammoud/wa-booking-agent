import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.generic import TemplateView

from conversations.models import Conversation, EndUser, Message
from conversations.tasks import schedule_buffer_check
from integrations.transcription import transcribe_audio
from integrations.whatsapp_client import download_media
from tenants.models import Tenant

logger = logging.getLogger(__name__)


class IntegrationsView(LoginRequiredMixin, TemplateView):
    """Staff-facing calendar-connection status page.

    Platform admins aren't scoped to any single tenant, so there's nothing
    to connect from here - just a neutral message for that role.
    """

    template_name = "integrations/integrations.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        tenant = None if user.role == user.Role.PLATFORM_ADMIN else user.tenant
        context["tenant"] = tenant
        context["connection"] = getattr(tenant, "calendar_connection", None) if tenant else None
        return context


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        return _handle_verification(request)
    return _handle_incoming(request)


def _handle_verification(request):
    if (
        request.GET.get("hub.mode") == "subscribe"
        and request.GET.get("hub.verify_token") == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
    ):
        return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
    return HttpResponse(status=403)


def _handle_incoming(request):
    if not _has_valid_signature(request):
        return HttpResponse(status=403)

    payload = json.loads(request.body)
    for message, tenant, end_user, conversation in _resolve_messages(payload):
        saved_message = _persist_message(message, conversation)
        if saved_message is not None:
            # Deliberately skipped for a duplicate - it was already (or is
            # already being) processed on first delivery.
            schedule_buffer_check(tenant.id, end_user.id, saved_message.id)

    return HttpResponse(status=200)


def _persist_message(message, conversation):
    """Create a Message row for `message`, or return None if it's a duplicate."""
    message_type = message.get("type", "")
    content = ""
    media_reference = ""
    if message_type == "text":
        content = message.get("text", {}).get("body", "")
    elif message_type in ("audio", "image"):
        media_reference = message.get(message_type, {}).get("id", "")

    try:
        with transaction.atomic():
            saved_message = Message.objects.create(
                conversation=conversation,
                direction=Message.Direction.INBOUND,
                message_type=message_type,
                content=content,
                media_reference=media_reference,
                whatsapp_message_id=message.get("id"),
                raw_payload=message,
            )
    except IntegrityError:
        logger.info("Duplicate webhook message id=%s, ignoring", message.get("id"))
        return None

    if message_type == "audio":
        # Synchronous in the webhook request, before this message ever
        # reaches the debounce buffer - the agent must see real text, not
        # a placeholder. A known latency tradeoff for this first pass; a
        # follow-up could move this into a Celery task ahead of the buffer
        # push if it becomes a real problem.
        _transcribe_and_store(conversation.tenant, saved_message)

    return saved_message


def _transcribe_and_store(tenant, message):
    audio_bytes = download_media(tenant, message.media_reference)
    if audio_bytes is None:
        return
    transcript = transcribe_audio(audio_bytes)
    if transcript:
        message.content = transcript
        message.save(update_fields=["content"])


def _resolve_messages(payload):
    """Yield (message, tenant, end_user, conversation) for every message in the payload.

    Skips changes with no "messages" key (e.g. status/read-receipt webhooks,
    which Meta delivers on the same field) and messages for an unrecognized
    phone_number_id (logged and ignored, not an error - could be a webhook
    for a tenant not yet in our system).
    """
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages")
            if not messages:
                continue

            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            tenant = Tenant.objects.filter(phone_number_id=phone_number_id).first()
            if tenant is None:
                logger.info("Ignoring webhook for unknown phone_number_id=%s", phone_number_id)
                continue

            contacts_by_wa_id = {c["wa_id"]: c for c in value.get("contacts", [])}

            for message in messages:
                sender = message.get("from")
                display_name = contacts_by_wa_id.get(sender, {}).get("profile", {}).get("name", "")
                end_user, _created = EndUser.objects.get_or_create(
                    tenant=tenant,
                    phone_number=sender,
                    defaults={"display_name": display_name},
                )
                conversation = _get_or_create_conversation(tenant, end_user)
                yield message, tenant, end_user, conversation


def _get_or_create_conversation(tenant, end_user):
    """The most recent still-open conversation (active, or awaiting the
    user's reply mid slot-filling), or a new active one if none exists."""
    conversation = (
        Conversation.objects.filter(
            tenant=tenant,
            end_user=end_user,
            status__in=[Conversation.Status.ACTIVE, Conversation.Status.AWAITING_USER],
        )
        .order_by("-last_message_at")
        .first()
    )
    if conversation is not None:
        return conversation
    return Conversation.objects.create(tenant=tenant, end_user=end_user)


def _has_valid_signature(request):
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
