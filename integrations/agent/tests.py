import datetime
import json
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
import requests
from django.utils import timezone

from bookings.models import Booking, Service
from conversations.models import Conversation, EndUser, Message
from integrations.agent import get_agent, memory
from integrations.agent.mock import MockAgent
from integrations.agent.openrouter import FALLBACK_REPLY, OpenRouterAgent
from integrations.agent.prompts import build_system_prompt
from integrations.agent.tools import MAX_SUGGESTED_SLOTS, execute_tool, serialize_tool_result


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


def _tool_call_completion(name, arguments, call_id="call_1"):
    return _fake_completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}
            ],
        }
    )


def test_openrouter_agent_executes_tool_and_returns_final_phrased_reply(tenant, conversation):
    tenant.working_hours = {"mon": ["09:00", "17:00"]}
    tenant.save()
    first = _tool_call_completion("check_availability", {"service": "Consultation"})
    second = _fake_completion({"role": "assistant", "content": "Here are a few times that work!"})

    with patch(
        "integrations.agent.openrouter.requests.post", side_effect=[first, second]
    ) as mock_post:
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "reply"
    assert result.text == "Here are a few times that work!"

    # Second call feeds the tool result back as a role:"tool" message.
    second_call_messages = mock_post.call_args_list[1].kwargs["json"]["messages"]
    assert second_call_messages[-1]["role"] == "tool"
    assert second_call_messages[-1]["tool_call_id"] == "call_1"
    assert "available_slots" in second_call_messages[-1]["content"]
    # No tools on the final-phrasing call - it must produce text, not another call.
    assert "tools" not in mock_post.call_args_list[1].kwargs["json"]


def test_openrouter_agent_falls_back_when_tool_name_unknown(conversation):
    first = _tool_call_completion("not_a_real_tool", {})

    with patch("integrations.agent.openrouter.requests.post", return_value=first):
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "reply"
    assert result.text == FALLBACK_REPLY


def test_openrouter_agent_falls_back_when_final_phrasing_call_fails(tenant, conversation):
    tenant.working_hours = {"mon": ["09:00", "17:00"]}
    tenant.save()
    first = _tool_call_completion("check_availability", {})

    with patch(
        "integrations.agent.openrouter.requests.post",
        side_effect=[
            first,
            requests.ConnectionError,
            requests.ConnectionError,
            requests.ConnectionError,
        ],
    ):
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "reply"
    assert result.text == FALLBACK_REPLY


def test_openrouter_agent_returns_reply_from_response(conversation):
    fake_response = _fake_completion({"role": "assistant", "content": "Sure, happy to help!"})

    with patch("integrations.agent.openrouter.requests.post", return_value=fake_response):
        result = OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert result.action == "reply"
    assert result.text == "Sure, happy to help!"


def test_openrouter_agent_includes_pending_intent_state_when_present(conversation):
    conversation.status = Conversation.Status.AWAITING_USER
    conversation.pending_intent_state = {"service": "Consultation", "date": "Thursday"}
    conversation.save()
    fake_response = _fake_completion({"role": "assistant", "content": "What time works?"})

    with patch(
        "integrations.agent.openrouter.requests.post", return_value=fake_response
    ) as mock_post:
        OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    system_content = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "Consultation" in system_content
    assert "Thursday" in system_content


def test_openrouter_agent_omits_pending_intent_note_when_empty(conversation):
    fake_response = _fake_completion({"role": "assistant", "content": "Hi!"})

    with patch(
        "integrations.agent.openrouter.requests.post", return_value=fake_response
    ) as mock_post:
        OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    system_content = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "already confirmed" not in system_content


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


@pytest.fixture
def service(tenant):
    return Service.objects.create(tenant=tenant, name="Consultation", duration_minutes=30)


def test_create_booking_tool_confirms_valid_request(tenant, conversation, service):
    conversation.status = Conversation.Status.AWAITING_USER
    conversation.pending_intent_state = {"service": "Consultation"}
    conversation.save()

    start = timezone.now() + datetime.timedelta(days=1)
    result = execute_tool(
        "create_booking",
        tenant,
        conversation,
        {"service_name": "Consultation", "start_time": start.isoformat()},
    )

    assert result["status"] == "confirmed"
    assert isinstance(result["booking"], Booking)
    assert result["booking"].end_user == conversation.end_user
    assert result["booking"].service == service

    conversation.refresh_from_db()
    assert conversation.status == Conversation.Status.ACTIVE
    assert conversation.pending_intent_state == {}


def test_create_booking_tool_errors_on_unknown_service(tenant, conversation):
    start = timezone.now() + datetime.timedelta(days=1)
    result = execute_tool(
        "create_booking",
        tenant,
        conversation,
        {"service_name": "Not A Real Service", "start_time": start.isoformat()},
    )

    assert result["status"] == "error"


def test_create_booking_tool_errors_on_unparseable_time(tenant, conversation, service):
    result = execute_tool(
        "create_booking",
        tenant,
        conversation,
        {"service_name": "Consultation", "start_time": "not a real date"},
    )

    assert result["status"] == "error"


def test_create_booking_tool_errors_when_slot_already_taken(tenant, conversation, service):
    start = timezone.now() + datetime.timedelta(days=1)
    Booking.objects.create(
        tenant=tenant,
        end_user=conversation.end_user,
        service=service,
        scheduled_start=start,
        scheduled_end=start + datetime.timedelta(minutes=30),
    )

    result = execute_tool(
        "create_booking",
        tenant,
        conversation,
        {"service_name": "Consultation", "start_time": start.isoformat()},
    )

    assert result["status"] == "error"


def test_build_system_prompt_states_working_hours_when_configured(tenant):
    tenant.working_hours = {"mon": ["09:00", "17:00"]}
    tenant.save()
    assert "Mon 09:00-17:00" in build_system_prompt(tenant)


def test_build_system_prompt_avoids_guessing_hours_when_unconfigured(tenant):
    prompt = build_system_prompt(tenant)
    assert "not yet configured" in prompt


_ALL_DAYS_OPEN = {
    day: ["00:00", "23:59"] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
}


def test_check_availability_tool_caps_results(tenant):
    tenant.working_hours = _ALL_DAYS_OPEN
    tenant.save()

    result = execute_tool("check_availability", tenant, None, {})

    assert len(result) == MAX_SUGGESTED_SLOTS


def test_check_availability_tool_pages_forward_with_after_date(tenant):
    tenant.working_hours = _ALL_DAYS_OPEN
    tenant.save()

    first_batch = execute_tool("check_availability", tenant, None, {})
    last_offered_date = first_batch[-1].start.date().isoformat()

    second_batch = execute_tool(
        "check_availability", tenant, None, {"after_date": last_offered_date}
    )

    assert all(slot.start.date().isoformat() > last_offered_date for slot in second_batch)


def test_serialize_tool_result_check_availability(tenant):
    tenant.working_hours = _ALL_DAYS_OPEN
    tenant.save()
    slots = execute_tool("check_availability", tenant, None, {})

    payload = json.loads(serialize_tool_result("check_availability", slots, tenant))

    assert len(payload["available_slots"]) == len(slots)


def test_serialize_tool_result_create_booking_confirmed(tenant, conversation, service):
    start = timezone.now() + datetime.timedelta(days=1)
    result = execute_tool(
        "create_booking",
        tenant,
        conversation,
        {"service_name": "Consultation", "start_time": start.isoformat()},
    )

    payload = json.loads(serialize_tool_result("create_booking", result, tenant))

    assert payload["status"] == "confirmed"
    assert payload["service"] == "Consultation"


def test_serialize_tool_result_create_booking_error(tenant, conversation):
    result = {"status": "error", "message": "Sorry, that time was just taken"}
    payload = json.loads(serialize_tool_result("create_booking", result, tenant))
    assert payload == result


def test_build_system_prompt_states_todays_date(tenant):
    # Without this, a partial date like "September 1st" is resolved against
    # the model's own training-data assumptions rather than reality - caused
    # a real wrong-year booking during live testing.
    prompt = build_system_prompt(tenant)
    today_local = timezone.now().astimezone(ZoneInfo(tenant.timezone))
    assert today_local.strftime("%Y-%m-%d") in prompt


def _add_messages(conversation, count, prefix="msg"):
    return [
        Message.objects.create(
            conversation=conversation,
            direction=Message.Direction.INBOUND if i % 2 == 0 else Message.Direction.OUTBOUND,
            message_type=Message.MessageType.TEXT,
            content=f"{prefix}-{i}",
        )
        for i in range(count)
    ]


def test_windowed_messages_returns_all_when_under_window(conversation):
    assert len(memory.windowed_messages(conversation)) == 1


def test_windowed_messages_caps_at_window_size(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    created = _add_messages(conv, memory.WINDOW_SIZE + 5)

    result = memory.windowed_messages(conv)

    assert len(result) == memory.WINDOW_SIZE
    assert [m.id for m in result] == [m.id for m in created[-memory.WINDOW_SIZE :]]


def test_pending_summary_messages_empty_below_batch_size(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    _add_messages(conv, memory.WINDOW_SIZE + memory.SUMMARY_BATCH_SIZE - 1)

    assert memory.pending_summary_messages(conv) == []


def test_pending_summary_messages_returns_aged_out_batch(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    created = _add_messages(conv, memory.WINDOW_SIZE + memory.SUMMARY_BATCH_SIZE)

    pending = memory.pending_summary_messages(conv)

    assert [m.id for m in pending] == [m.id for m in created[: memory.SUMMARY_BATCH_SIZE]]


def test_pending_summary_messages_respects_existing_checkpoint(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    created = _add_messages(conv, memory.WINDOW_SIZE + memory.SUMMARY_BATCH_SIZE)
    conv.context_summary_through_message_id = created[4].id
    conv.save()

    pending = memory.pending_summary_messages(conv)

    assert all(m.id > created[4].id for m in pending)


def test_persist_summary_updates_conversation(conversation):
    memory.persist_summary(conversation, "A short summary.", 42)

    conversation.refresh_from_db()
    assert conversation.context_summary == "A short summary."
    assert conversation.context_summary_through_message_id == 42


def test_openrouter_agent_bounds_history_regardless_of_conversation_length(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    _add_messages(conv, memory.WINDOW_SIZE + memory.SUMMARY_BATCH_SIZE + 5)
    fake_response = _fake_completion({"role": "assistant", "content": "Got it"})

    with patch(
        "integrations.agent.openrouter.requests.post", return_value=fake_response
    ) as mock_post:
        OpenRouterAgent().respond(conv, [])

    # One summarization call, one real reply call - never grows with history.
    assert mock_post.call_count == 2
    reply_call_messages = mock_post.call_args_list[-1].kwargs["json"]["messages"]
    assert len(reply_call_messages) == 1 + memory.WINDOW_SIZE


def test_openrouter_agent_summary_appears_in_system_content_after_update(tenant, end_user):
    conv = Conversation.objects.create(tenant=tenant, end_user=end_user)
    _add_messages(conv, memory.WINDOW_SIZE + memory.SUMMARY_BATCH_SIZE)
    summary_response = _fake_completion(
        {"role": "assistant", "content": "Customer wants a consultation next week."}
    )
    reply_response = _fake_completion({"role": "assistant", "content": "Sure!"})

    with patch(
        "integrations.agent.openrouter.requests.post",
        side_effect=[summary_response, reply_response],
    ) as mock_post:
        OpenRouterAgent().respond(conv, [])

    conv.refresh_from_db()
    assert conv.context_summary == "Customer wants a consultation next week."
    reply_call_messages = mock_post.call_args_list[-1].kwargs["json"]["messages"]
    assert "Customer wants a consultation next week." in reply_call_messages[0]["content"]


def test_openrouter_agent_skips_summarization_when_not_enough_aged_out(conversation):
    fake_response = _fake_completion({"role": "assistant", "content": "Hi!"})

    with patch(
        "integrations.agent.openrouter.requests.post", return_value=fake_response
    ) as mock_post:
        OpenRouterAgent().respond(conversation, list(conversation.messages.all()))

    assert mock_post.call_count == 1
