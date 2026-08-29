import json
from unittest.mock import Mock, patch

import pytest
import requests

from conversations.models import Conversation, EndUser, Message
from integrations.agent import get_agent
from integrations.agent.mock import MockAgent
from integrations.agent.openrouter import FALLBACK_REPLY, OpenRouterAgent


@pytest.fixture
def end_user(tenant):
    return EndUser.objects.create(tenant=tenant, phone_number="+15550001111")


@pytest.fixture
def conversation(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    Message.objects.create(
        conversation=conv,
        direction=Message.Direction.INBOUND,
        message_type=Message.MessageType.TEXT,
        content="I'd like to book a consultation",
    )
    return conv


def _fake_completion(message):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"choices": [{"message": message}]}
    return response


def test_get_agent_defaults_to_mock(settings):
    settings.AGENT_BACKEND = "mock"
    assert isinstance(get_agent(), MockAgent)


def test_get_agent_returns_openrouter_when_configured(settings):
    settings.AGENT_BACKEND = "openrouter"
    assert isinstance(get_agent(), OpenRouterAgent)


def test_openrouter_agent_returns_tool_call_from_response(conversation):
    fake_response = _fake_completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "function": {
                        "name": "check_availability",
                        "arguments": json.dumps({"service": "Consultation"}),
                    }
                }
            ],
        }
    )

    with patch("integrations.agent.openrouter.requests.post", return_value=fake_response):
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "tool_call"
    assert result.tool == "check_availability"
    assert result.tool_args == {"service": "Consultation"}


def test_openrouter_agent_returns_reply_from_response(conversation):
    fake_response = _fake_completion({"role": "assistant", "content": "Sure, happy to help!"})

    with patch("integrations.agent.openrouter.requests.post", return_value=fake_response):
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "reply"
    assert result.text == "Sure, happy to help!"


def test_openrouter_agent_sends_full_conversation_history(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    Message.objects.create(
        conversation=conv,
        direction=Message.Direction.INBOUND,
        message_type=Message.MessageType.TEXT,
        content="Hi",
    )
    Message.objects.create(
        conversation=conv,
        direction=Message.Direction.OUTBOUND,
        message_type=Message.MessageType.TEXT,
        content="Hello, how can I help?",
    )
    new_message = Message.objects.create(
        conversation=conv,
        direction=Message.Direction.INBOUND,
        message_type=Message.MessageType.TEXT,
        content="I want to book Thursday",
    )
    fake_response = _fake_completion({"role": "assistant", "content": "Got it!"})

    with patch(
        "integrations.agent.openrouter.requests.post", return_value=fake_response
    ) as mock_post:
        OpenRouterAgent().respond(conv, [new_message])

    sent_messages = mock_post.call_args.kwargs["json"]["messages"]
    roles_and_content = [(m["role"], m["content"]) for m in sent_messages]
    assert roles_and_content == [
        ("system", roles_and_content[0][1]),
        ("user", "Hi"),
        ("assistant", "Hello, how can I help?"),
        ("user", "I want to book Thursday"),
    ]


def test_openrouter_agent_falls_back_on_request_failure(conversation):
    with patch(
        "integrations.agent.openrouter.requests.post",
        side_effect=requests.ConnectionError,
    ):
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "reply"
    assert result.text == FALLBACK_REPLY
