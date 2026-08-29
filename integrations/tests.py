import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import pytest
import requests
from django.urls import reverse

from conversations import buffer
from conversations.models import Conversation, EndUser, Message
from conversations.tasks import check_and_drain_buffer
from integrations.agent.mock import MockAgent
from integrations.agent.tools import ask_clarification, execute_tool
from integrations.transcription import transcribe_audio
from integrations.whatsapp_client import download_media, send_text_message

MINIMAL_PAYLOAD = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()


@pytest.fixture(autouse=True)
def _no_real_celery_dispatch():
    """Prevent every webhook test in this module from leaking a real
    countdown task into the broker - schedule_buffer_check() calls
    check_and_drain_buffer.apply_async() for real on any successfully
    persisted inbound message. Without this, that task fires later (after
    the test's DB transaction has rolled back) against a live dev Celery
    worker, producing "missing tenant/end_user" error noise. Buffer pushes
    themselves are unaffected - only the broker dispatch is stubbed.
    """
    with patch("conversations.tasks.check_and_drain_buffer.apply_async"):
        yield


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


def test_webhook_reuses_awaiting_user_conversation_mid_slot_filling(client, settings, tenant):
    # A reply arriving while the agent is mid slot-filling (ask_clarification
    # already set status=AWAITING_USER) must attach to that same conversation,
    # not spawn a duplicate active one.
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()
    end_user = EndUser.objects.create(tenant=tenant, phone_number="16315551181")
    conversation = Conversation.objects.create(
        tenant=tenant, end_user=end_user, status=Conversation.Status.AWAITING_USER
    )

    _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")

    assert Conversation.objects.filter(tenant=tenant, end_user=end_user).count() == 1
    assert Message.objects.get(whatsapp_message_id="wamid.sample-1").conversation == conversation


def test_webhook_persists_inbound_message(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()

    _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")

    message = Message.objects.get(whatsapp_message_id="wamid.sample-1")
    assert message.direction == Message.Direction.INBOUND
    assert message.message_type == Message.MessageType.TEXT
    assert message.content == "Hi there"


def test_webhook_dedupes_on_replayed_whatsapp_message_id(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()

    first = _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")
    second = _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")

    assert first.status_code == 200
    assert second.status_code == 200
    assert Message.objects.filter(whatsapp_message_id="wamid.sample-1").count() == 1


def test_webhook_buffers_new_message_but_not_a_duplicate(client, settings, tenant, caplog):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()

    _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")
    message = Message.objects.get(whatsapp_message_id="wamid.sample-1")
    end_user = EndUser.objects.get(tenant=tenant, phone_number="16315551181")
    assert buffer.peek(tenant.id, end_user.id) == [message.id]

    with caplog.at_level("INFO"):
        response = _post_webhook(client, SAMPLE_MESSAGE_PAYLOAD, "app-secret")
    assert response.status_code == 200
    assert "Duplicate webhook message" in caplog.text
    # Still just the one buffered id - the duplicate was never scheduled.
    assert buffer.peek(tenant.id, end_user.id) == [message.id]

    buffer.drain(tenant.id, end_user.id)


def test_send_text_message_posts_expected_shape(tenant):
    tenant.phone_number_id = "123456123"
    tenant.whatsapp_access_token = b"real-token"
    tenant.save()

    mock_response = Mock()
    mock_response.json.return_value = {"messages": [{"id": "wamid.outbound-1"}]}
    mock_response.raise_for_status.return_value = None

    with patch("integrations.whatsapp_client.requests.post", return_value=mock_response) as post:
        result = send_text_message(tenant, "16315551181", "Hi there")

    assert result == {"messages": [{"id": "wamid.outbound-1"}]}
    args, kwargs = post.call_args
    assert args[0] == "https://graph.facebook.com/v21.0/123456123/messages"
    assert kwargs["headers"] == {"Authorization": "Bearer real-token"}
    assert kwargs["json"] == {
        "messaging_product": "whatsapp",
        "to": "16315551181",
        "type": "text",
        "text": {"body": "Hi there"},
    }


def test_send_text_message_returns_none_on_failure(tenant, caplog):
    tenant.phone_number_id = "123456123"
    tenant.whatsapp_access_token = b"real-token"
    tenant.save()

    with patch(
        "integrations.whatsapp_client.requests.post",
        side_effect=requests.ConnectionError("boom"),
    ):
        with caplog.at_level("ERROR"):
            result = send_text_message(tenant, "16315551181", "Hi there")

    assert result is None
    assert "Failed to send WhatsApp message" in caplog.text


def test_mock_agent_returns_tool_call_on_booking_keyword():
    agent = MockAgent()
    messages = [Message(content="Hi"), Message(content="I'd like to book an appointment")]
    response = agent.respond(conversation=None, messages=messages)
    assert response.action == "tool_call"
    assert response.tool == "check_availability"


def test_mock_agent_returns_canned_reply_otherwise():
    agent = MockAgent()
    messages = [Message(content="Hello there"), Message(content="Just saying hi")]
    response = agent.respond(conversation=None, messages=messages)
    assert response.action == "reply"
    assert response.text == "Thanks for your message, how can I help?"


def test_ask_clarification_returns_text_unchanged():
    assert ask_clarification("What date works for you?") == "What date works for you?"


def test_execute_tool_dispatches_check_availability(tenant):
    # tenant fixture has no working_hours configured - real computation
    # correctly returns no slots rather than a hardcoded fake count.
    result = execute_tool("check_availability", tenant, None, {})
    assert result == []


def test_execute_tool_dispatches_ask_clarification(tenant):
    end_user = EndUser.objects.create(tenant=tenant, phone_number="+15550002222")
    conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)

    result = execute_tool(
        "ask_clarification",
        tenant,
        conversation,
        {"question": "Which day?", "known_slots": {"service": "Consultation"}},
    )

    assert result == "Which day?"
    conversation.refresh_from_db()
    assert conversation.status == Conversation.Status.AWAITING_USER
    assert conversation.pending_intent_state == {"service": "Consultation"}


def test_execute_tool_raises_on_unknown_tool(tenant):
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool("not_a_real_tool", tenant, None, {})


def test_full_pipeline_inbound_booking_message_to_outbound_reply(client, settings, tenant):
    """Inbound webhook -> persist -> buffer -> MockAgent tool_call ->
    check_availability -> outbound reply, with send_text_message mocked
    (no real network call). Simulates the real webhook payload rather than
    calling internal functions directly, unlike the narrower routing tests
    above.
    """
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    all_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    tenant.working_hours = {day: ["09:00", "17:00"] for day in all_days}
    tenant.save()

    booking_payload = json.loads(json.dumps(SAMPLE_MESSAGE_PAYLOAD))
    inner_message = booking_payload["entry"][0]["changes"][0]["value"]["messages"][0]
    inner_message["id"] = "wamid.pipeline-booking-1"
    inner_message["text"]["body"] = "I'd like to book an appointment please"

    with patch("conversations.tasks.check_and_drain_buffer.apply_async") as mock_apply_async:
        response = _post_webhook(client, booking_payload, "app-secret")
    assert response.status_code == 200

    tenant_id, end_user_id, scheduled_at = mock_apply_async.call_args.kwargs["args"]

    with patch(
        "conversations.tasks.send_text_message",
        return_value={"messages": [{"id": "wamid.pipeline-reply-1"}]},
    ) as mock_send:
        check_and_drain_buffer(tenant_id, end_user_id, scheduled_at)

    reply_text = mock_send.call_args.args[2]
    assert reply_text.startswith("Here are some available times:")

    end_user = EndUser.objects.get(tenant=tenant, phone_number="16315551181")
    conversation = Conversation.objects.get(tenant=tenant, end_user=end_user)
    outbound = conversation.messages.get(direction=Message.Direction.OUTBOUND)
    assert outbound.content == reply_text
    assert outbound.whatsapp_message_id == "wamid.pipeline-reply-1"


def test_download_media_fetches_signed_url_then_content(tenant):
    tenant.whatsapp_access_token = b"real-token"
    tenant.save()

    meta_response = Mock()
    meta_response.raise_for_status.return_value = None
    meta_response.json.return_value = {"url": "https://lookaside.example/media/abc"}

    content_response = Mock()
    content_response.raise_for_status.return_value = None
    content_response.content = b"raw-audio-bytes"

    with patch(
        "integrations.whatsapp_client.requests.get",
        side_effect=[meta_response, content_response],
    ) as mock_get:
        result = download_media(tenant, "media-id-123")

    assert result == b"raw-audio-bytes"
    first_call, second_call = mock_get.call_args_list
    assert first_call.args[0] == "https://graph.facebook.com/v21.0/media-id-123"
    assert second_call.args[0] == "https://lookaside.example/media/abc"
    assert first_call.kwargs["headers"] == {"Authorization": "Bearer real-token"}
    assert second_call.kwargs["headers"] == {"Authorization": "Bearer real-token"}


def test_download_media_returns_none_on_failure(tenant, caplog):
    tenant.whatsapp_access_token = b"real-token"
    tenant.save()

    with patch(
        "integrations.whatsapp_client.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ):
        with caplog.at_level("ERROR"):
            result = download_media(tenant, "media-id-123")

    assert result is None
    assert "Failed to download media" in caplog.text


def test_transcribe_audio_returns_text_on_success(settings):
    settings.OPENROUTER_API_KEY = "or-key"
    settings.TRANSCRIPTION_MODEL = "openai/whisper-1"

    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"text": "Hello, I need an appointment"}

    with patch("integrations.transcription.requests.post", return_value=fake_response) as mock_post:
        result = transcribe_audio(b"fake-audio-bytes")

    assert result == "Hello, I need an appointment"
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer or-key"}
    assert kwargs["json"]["model"] == "openai/whisper-1"
    assert kwargs["json"]["input_audio"]["format"] == "ogg"


def test_transcribe_audio_returns_none_on_failure(caplog):
    with patch(
        "integrations.transcription.requests.post",
        side_effect=requests.ConnectionError("boom"),
    ):
        with caplog.at_level("ERROR"):
            result = transcribe_audio(b"fake-audio-bytes")

    assert result is None
    assert "Audio transcription failed" in caplog.text


def test_webhook_transcribes_audio_message_before_buffering(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()

    audio_payload = json.loads(json.dumps(SAMPLE_MESSAGE_PAYLOAD))
    inner_message = audio_payload["entry"][0]["changes"][0]["value"]["messages"][0]
    inner_message["id"] = "wamid.audio-1"
    inner_message["type"] = "audio"
    inner_message["audio"] = {"id": "meta-media-id-1"}
    del inner_message["text"]

    with (
        patch("integrations.views.download_media", return_value=b"raw-bytes") as mock_download,
        patch(
            "integrations.views.transcribe_audio", return_value="Book me a consultation"
        ) as mock_transcribe,
    ):
        response = _post_webhook(client, audio_payload, "app-secret")

    assert response.status_code == 200
    mock_download.assert_called_once_with(tenant, "meta-media-id-1")
    mock_transcribe.assert_called_once_with(b"raw-bytes")

    message = Message.objects.get(whatsapp_message_id="wamid.audio-1")
    assert message.message_type == "audio"
    assert message.media_reference == "meta-media-id-1"
    assert message.content == "Book me a consultation"


def test_webhook_leaves_audio_content_empty_when_transcription_fails(client, settings, tenant):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    tenant.phone_number_id = "123456123"
    tenant.save()

    audio_payload = json.loads(json.dumps(SAMPLE_MESSAGE_PAYLOAD))
    inner_message = audio_payload["entry"][0]["changes"][0]["value"]["messages"][0]
    inner_message["id"] = "wamid.audio-2"
    inner_message["type"] = "audio"
    inner_message["audio"] = {"id": "meta-media-id-2"}
    del inner_message["text"]

    with (
        patch("integrations.views.download_media", return_value=None),
        patch("integrations.views.transcribe_audio") as mock_transcribe,
    ):
        response = _post_webhook(client, audio_payload, "app-secret")

    assert response.status_code == 200
    mock_transcribe.assert_not_called()

    message = Message.objects.get(whatsapp_message_id="wamid.audio-2")
    assert message.content == ""


def test_integrations_page_requires_login(client):
    response = client.get(reverse("integrations"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_integrations_page_shows_no_connection_state_for_staff(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("integrations"))
    assert response.status_code == 200
    assert response.context["connection"] is None
    assert b"No calendar connected yet" in response.content


def test_integrations_page_shows_neutral_message_for_platform_admin(client, platform_admin_user):
    client.force_login(platform_admin_user)
    response = client.get(reverse("integrations"))
    assert response.status_code == 200
    assert response.context["tenant"] is None
    assert b"Platform admins" in response.content
