from django.urls import reverse


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
