import hashlib
import hmac
import json

from django.urls import reverse

from conversations.models import Conversation, EndUser

MINIMAL_PAYLOAD = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

# Based on Meta's documented WhatsApp Cloud API webhook payload format.
SAMPLE_MESSAGE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA_ID",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15551234567",
                            "phone_number_id": "123456123",
                        },
                        "contacts": [{"profile": {"name": "Jane Doe"}, "wa_id": "16315551181"}],
                        "messages": [
                            {
                                "from": "16315551181",
                                "id": "wamid.sample-1",
                                "timestamp": "1603059201",
                                "type": "text",
                                "text": {"body": "Hi there"},
                            }
                        ],
                    },
                }
            ],
        }
    ],
}


def _signed(body, secret):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post_webhook(client, payload_dict, secret):
    body = json.dumps(payload_dict).encode()
    return client.post(
        reverse("whatsapp-webhook"),
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_signed(body, secret),
    )


def test_webhook_handshake_echoes_challenge_with_correct_token(client, settings):
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "expected-token"
    response = client.get(
        reverse("whatsapp-webhook"),
        {"hub.mode": "subscribe", "hub.verify_token": "expected-token", "hub.challenge": "12345"},
    )
    assert response.status_code == 200
    assert response.content == b"12345"


def test_webhook_handshake_rejects_wrong_token(client, settings):
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "expected-token"
    response = client.get(
        reverse("whatsapp-webhook"),
        {"hub.mode": "subscribe", "hub.verify_token": "wrong-token", "hub.challenge": "12345"},
    )
    assert response.status_code == 403


def test_webhook_handshake_rejects_wrong_mode(client, settings):
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "expected-token"
    response = client.get(
        reverse("whatsapp-webhook"),
        {"hub.mode": "unsubscribe", "hub.verify_token": "expected-token", "hub.challenge": "1"},
    )
    assert response.status_code == 403


def test_webhook_post_accepts_correctly_signed_payload(client, settings):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    response = client.post(
        reverse("whatsapp-webhook"),
        data=MINIMAL_PAYLOAD,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_signed(MINIMAL_PAYLOAD, "app-secret"),
    )
    assert response.status_code == 200


def test_webhook_post_rejects_incorrectly_signed_payload(client, settings):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    response = client.post(
        reverse("whatsapp-webhook"),
        data=MINIMAL_PAYLOAD,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_signed(MINIMAL_PAYLOAD, "wrong-secret"),
    )
    assert response.status_code == 403


def test_webhook_post_rejects_missing_signature(client, settings):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    response = client.post(
        reverse("whatsapp-webhook"), data=MINIMAL_PAYLOAD, content_type="application/json"
    )
    assert response.status_code == 403


def test_webhook_resolves_tenant_and_creates_end_user_and_conversation(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()

    response = _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")

    assert response.status_code == 200
    end_user = EndUser.objects.get(tenant=tenant, phone_number="16315551181")
    assert end_user.display_name == "Jane Doe"
    conversation = Conversation.objects.get(tenant=tenant, end_user=end_user)
    assert conversation.status == Conversation.Status.ACTIVE


def test_webhook_ignores_unknown_phone_number_id(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    # tenant.phone_number_id doesn't match SAMPLE_MESSAGE_PAYLOAD's "123456123".

    response = _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")

    assert response.status_code == 200
    assert not EndUser.objects.filter(phone_number="16315551181").exists()


def test_webhook_reuses_existing_active_conversation(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()
    end_user = EndUser.objects.create(tenant=tenant, phone_number="16315551181")
    Conversation.objects.create(tenant=tenant, end_user=end_user, status=Conversation.Status.ACTIVE)

    _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")

    assert Conversation.objects.filter(tenant=tenant, end_user=end_user).count() == 1
