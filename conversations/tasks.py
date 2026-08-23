"""Debounce buffer: wait for a pause in a user's messages before replying.

On each inbound message, schedule_buffer_check() pushes it onto a Redis
buffer (see conversations/buffer.py) and schedules check_and_drain_buffer to
run after DEBOUNCE_WINDOW_SECONDS, passing along the timestamp of *this*
push as scheduled_at.

When that delayed task fires, it re-reads the buffer's current last-message
timestamp. If a newer message has arrived since scheduled_at, a
later-scheduled check owns processing, so this one no-ops - cheaply
filtering out every stale check but the genuinely-last one. The actual
correctness guarantee against double-processing is buffer.drain()'s
Redis transaction, not this timestamp check (see that module for why).
"""

import logging

from celery import shared_task
from django.conf import settings

from conversations import buffer
from conversations.models import Conversation, EndUser
from integrations.whatsapp_client import send_text_message
from tenants.models import Tenant

logger = logging.getLogger(__name__)

# STUB reply - a real agent pipeline replaces this in a later sprint.
STUB_REPLY_TEXT = "Got your message!"


def schedule_buffer_check(tenant_id, end_user_id, message_id):
    scheduled_at = buffer.push_message(tenant_id, end_user_id, message_id)
    check_and_drain_buffer.apply_async(
        args=[tenant_id, end_user_id, scheduled_at],
        countdown=settings.DEBOUNCE_WINDOW_SECONDS,
    )


@shared_task
def check_and_drain_buffer(tenant_id, end_user_id, scheduled_at):
    last_message_at = buffer.get_last_message_at(tenant_id, end_user_id)
    if last_message_at is None or last_message_at > scheduled_at:
        return

    message_ids = buffer.drain(tenant_id, end_user_id)
    if not message_ids:
        return

    _process_buffered_messages(tenant_id, end_user_id, message_ids)


def _process_buffered_messages(tenant_id, end_user_id, message_ids):
    tenant = Tenant.objects.filter(id=tenant_id).first()
    end_user = EndUser.objects.filter(id=end_user_id).first()
    if tenant is None or end_user is None:
        logger.error("Buffer drained for missing tenant=%s end_user=%s", tenant_id, end_user_id)
        return

    conversation = (
        Conversation.objects.filter(
            tenant=tenant, end_user=end_user, status=Conversation.Status.ACTIVE
        )
        .order_by("-last_message_at")
        .first()
    )

    result = send_text_message(tenant, end_user.phone_number, STUB_REPLY_TEXT)
    if result is None:
        logger.error(
            "Failed to send reply for tenant=%s end_user=%s buffered_message_ids=%s",
            tenant_id,
            end_user_id,
            message_ids,
        )
        return

    logger.info(
        "Sent reply for tenant=%s end_user=%s buffered_message_ids=%s conversation=%s",
        tenant_id,
        end_user_id,
        message_ids,
        conversation.id if conversation else None,
    )
