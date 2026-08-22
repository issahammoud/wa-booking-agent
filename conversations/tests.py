import pytest
from django.db import IntegrityError, transaction

from conversations.models import Conversation, EndUser, Message


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
