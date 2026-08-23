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
