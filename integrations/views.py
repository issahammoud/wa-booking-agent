import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from conversations.models import Conversation, EndUser, Message
from tenants.models import Tenant

logger = logging.getLogger(__name__)


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
    for message, _tenant, _end_user, conversation in _resolve_messages(payload):
        _persist_message(message, conversation)

    return HttpResponse(status=200)


def _persist_message(message, conversation):
    message_type = message.get("type", "")
    content = ""
    media_reference = ""
    if message_type == "text":
        content = message.get("text", {}).get("body", "")
    elif message_type in ("audio", "image"):
        media_reference = message.get(message_type, {}).get("id", "")

    try:
        with transaction.atomic():
            Message.objects.create(
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
                conversation, _created = Conversation.objects.get_or_create(
                    tenant=tenant, end_user=end_user, status=Conversation.Status.ACTIVE
                )
                yield message, tenant, end_user, conversation


def _has_valid_signature(request):
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
