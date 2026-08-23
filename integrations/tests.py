import hashlib
import hmac
import json

from django.urls import reverse

MINIMAL_PAYLOAD = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()


def _signed(body, secret):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


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
