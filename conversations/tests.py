from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from conversations import buffer
from conversations.models import Conversation, EndUser, Message
from conversations.tasks import check_and_drain_buffer


@pytest.fixture
def end_user(tenant):
    return EndUser.objects.create(tenant=tenant, phone_number="+15550009999")


def test_end_user_unique_per_tenant_phone_number(tenant, other_tenant):
    EndUser.objects.create(tenant=tenant, phone_number="+15550000001")

    # Same phone number, different tenant: allowed.
    EndUser.objects.create(tenant=other_tenant, phone_number="+15550000001")

    # Same phone number, same tenant: rejected.
    with pytest.raises(IntegrityError), transaction.atomic():
        EndUser.objects.create(tenant=tenant, phone_number="+15550000001")


def test_message_unique_whatsapp_message_id(tenant):
    end_user = EndUser.objects.create(tenant=tenant, phone_number="+15550000002")
    conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)
    Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        message_type=Message.MessageType.TEXT,
        whatsapp_message_id="wamid.duplicate-test",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(
            conversation=conversation,
            direction=Message.Direction.INBOUND,
            message_type=Message.MessageType.TEXT,
            whatsapp_message_id="wamid.duplicate-test",
        )


def test_staff_user_cannot_see_other_tenants_conversations(
    client, tenant, other_tenant, staff_user
):
    end_user_a = EndUser.objects.create(tenant=tenant, phone_number="+15550005555")
    end_user_b = EndUser.objects.create(tenant=other_tenant, phone_number="+15550006666")
    conversation_a = Conversation.objects.create(tenant=tenant, end_user=end_user_a)
    conversation_b = Conversation.objects.create(tenant=other_tenant, end_user=end_user_b)

    client.force_login(staff_user)
    response = client.get(reverse("conversation-list"))

    visible = list(response.context["conversation_list"])
    assert conversation_a in visible
    assert conversation_b not in visible


def test_platform_admin_sees_all_tenants_conversations(
    client, tenant, other_tenant, platform_admin_user
):
    end_user_a = EndUser.objects.create(tenant=tenant, phone_number="+15550007777")
    end_user_b = EndUser.objects.create(tenant=other_tenant, phone_number="+15550008888")
    conversation_a = Conversation.objects.create(tenant=tenant, end_user=end_user_a)
    conversation_b = Conversation.objects.create(tenant=other_tenant, end_user=end_user_b)

    client.force_login(platform_admin_user)
    response = client.get(reverse("conversation-list"))

    visible = list(response.context["conversation_list"])
    assert conversation_a in visible
    assert conversation_b in visible


def test_anonymous_user_redirected_to_login(client, db):
    response = client.get(reverse("conversation-list"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_debounce_buffer_processes_rapid_messages_exactly_once(tenant, end_user):
    Conversation.objects.create(tenant=tenant, end_user=end_user)

    ts1 = buffer.push_message(tenant.id, end_user.id, 101)
    buffer.push_message(tenant.id, end_user.id, 102)
    ts3 = buffer.push_message(tenant.id, end_user.id, 103)

    with patch(
        "conversations.tasks.send_text_message",
        return_value={"messages": [{"id": "wamid.reply-1"}]},
    ) as mock_send:
        # The earliest-scheduled check should no-op: a newer message (102,
        # 103) arrived after ts1, so a later-scheduled check owns this.
        check_and_drain_buffer(tenant.id, end_user.id, ts1)
        mock_send.assert_not_called()
        assert buffer.peek(tenant.id, end_user.id) == [101, 102, 103]

        # The latest-scheduled check should process all three, exactly once.
        check_and_drain_buffer(tenant.id, end_user.id, ts3)
        mock_send.assert_called_once()

    assert buffer.peek(tenant.id, end_user.id) == []


def test_successful_reply_logged_as_outbound_message_after_inbound(tenant, end_user):
    conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)
    Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        message_type=Message.MessageType.TEXT,
        content="Hello",
        whatsapp_message_id="wamid.inbound-1",
    )

    ts = buffer.push_message(tenant.id, end_user.id, 999)
    with patch(
        "conversations.tasks.send_text_message",
        return_value={"messages": [{"id": "wamid.outbound-1"}]},
    ):
        check_and_drain_buffer(tenant.id, end_user.id, ts)

    messages = list(conversation.messages.order_by("created_at"))
    assert [m.direction for m in messages] == [
        Message.Direction.INBOUND,
        Message.Direction.OUTBOUND,
    ]
    outbound = messages[1]
    assert outbound.content == "Got your message!"
    assert outbound.whatsapp_message_id == "wamid.outbound-1"


def test_failed_reply_is_not_logged_as_outbound_message(tenant, end_user, caplog):
    conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)

    ts = buffer.push_message(tenant.id, end_user.id, 998)
    with patch("conversations.tasks.send_text_message", return_value=None):
        with caplog.at_level("ERROR"):
            check_and_drain_buffer(tenant.id, end_user.id, ts)

    assert "Failed to send reply" in caplog.text
    assert not conversation.messages.filter(direction=Message.Direction.OUTBOUND).exists()


def test_gap_longer_than_debounce_window_triggers_two_processing_runs(tenant, end_user):
    conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)

    with patch(
        "conversations.tasks.send_text_message",
        side_effect=[
            {"messages": [{"id": "wamid.reply-a"}]},
            {"messages": [{"id": "wamid.reply-a-2"}]},
        ],
    ) as mock_send:
        # First burst: pushed and drained (simulating its debounce window
        # having already elapsed with no further messages).
        ts_a = buffer.push_message(tenant.id, end_user.id, 201)
        check_and_drain_buffer(tenant.id, end_user.id, ts_a)
        assert mock_send.call_count == 1

        # A real gap later, a second unrelated burst arrives.
        ts_b = buffer.push_message(tenant.id, end_user.id, 202)
        check_and_drain_buffer(tenant.id, end_user.id, ts_b)
        assert mock_send.call_count == 2

    # Two independent replies, not deduped into one.
    outbound_count = conversation.messages.filter(direction=Message.Direction.OUTBOUND).count()
    assert outbound_count == 2


def test_buffer_is_empty_after_processing_no_reprocessing_on_late_check(tenant, end_user):
    Conversation.objects.create(tenant=tenant, end_user=end_user)

    ts = buffer.push_message(tenant.id, end_user.id, 301)
    with patch(
        "conversations.tasks.send_text_message",
        return_value={"messages": [{"id": "wamid.reply-b"}]},
    ) as mock_send:
        check_and_drain_buffer(tenant.id, end_user.id, ts)
        assert mock_send.call_count == 1
        assert buffer.peek(tenant.id, end_user.id) == []

        # A stale/redelivered check for the same (now-drained) slot must not
        # reprocess - get_last_message_at is None (cleared by drain), so
        # this hits the "is None" branch and no-ops.
        check_and_drain_buffer(tenant.id, end_user.id, ts)
        assert mock_send.call_count == 1


def test_concurrent_checks_for_same_slot_only_process_once(tenant, end_user):
    """Simulates Celery's at-least-once delivery redelivering the same task."""
    conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)

    ts = buffer.push_message(tenant.id, end_user.id, 401)
    with patch(
        "conversations.tasks.send_text_message",
        return_value={"messages": [{"id": "wamid.reply-c"}]},
    ) as mock_send:
        # Both calls pass the timestamp check (same scheduled_at, nothing
        # newer has been pushed) - the transactional drain is what ensures
        # only the first actually has messages to process.
        check_and_drain_buffer(tenant.id, end_user.id, ts)
        check_and_drain_buffer(tenant.id, end_user.id, ts)

    assert mock_send.call_count == 1
    assert conversation.messages.filter(direction=Message.Direction.OUTBOUND).count() == 1
