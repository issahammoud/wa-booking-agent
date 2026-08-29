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
from zoneinfo import ZoneInfo

from celery import shared_task
from django.conf import settings

from conversations import buffer
from conversations.models import Conversation, EndUser, Message
from integrations.agent import get_agent
from integrations.agent.tools import execute_tool
from integrations.whatsapp_client import send_text_message
from tenants.models import Tenant

logger = logging.getLogger(__name__)


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
            tenant=tenant,
            end_user=end_user,
            status__in=[Conversation.Status.ACTIVE, Conversation.Status.AWAITING_USER],
        )
        .order_by("-last_message_at")
        .first()
    )
    if conversation is None:
        # Shouldn't happen in the real flow (the webhook always gets/creates
        # one before scheduling a check) - defensive, not expected.
        logger.error(
            "Buffer drained but no active/awaiting conversation for tenant=%s end_user=%s",
            tenant_id,
            end_user_id,
        )
        return

    messages = list(Message.objects.filter(id__in=message_ids).order_by("created_at"))
    reply_text = _get_reply_text(tenant, conversation, messages)

    result = send_text_message(tenant, end_user.phone_number, reply_text)
    if result is None:
        # Policy: a failed send is never logged as a Message row - a Message
        # represents something that actually reached the conversation, and a
        # failed send was never seen by the end user. Only the error is
        # logged; the inbound messages that triggered this remain in
        # Postgres either way (persisted by the webhook, independent of
        # whether the reply succeeds).
        logger.error(
            "Failed to send reply for tenant=%s end_user=%s buffered_message_ids=%s",
            tenant_id,
            end_user_id,
            message_ids,
        )
        return

    whatsapp_message_id = (result.get("messages") or [{}])[0].get("id") or None
    Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        message_type=Message.MessageType.TEXT,
        content=reply_text,
        whatsapp_message_id=whatsapp_message_id,
        raw_payload=result,
    )


def _get_reply_text(tenant, conversation, messages):
    response = get_agent().respond(conversation, messages)
    if response.action == "reply":
        return response.text

    tool_result = execute_tool(response.tool, tenant, conversation, response.tool_args)
    return _format_tool_result(response.tool, tool_result)


def _format_tool_result(tool_name, result):
    if tool_name == "check_availability":
        if not result:
            return "Sorry, I don't see any open slots in the next few days."
        slots = ", ".join(slot.start.strftime("%a %b %d, %H:%M") for slot in result)
        return f"Here are some available times: {slots}"
    if tool_name == "create_booking":
        return _format_booking_result(result)
    return str(result)


def _format_booking_result(result):
    if result["status"] != "confirmed":
        return result["message"]
    booking = result["booking"]
    local_start = booking.scheduled_start.astimezone(ZoneInfo(booking.tenant.timezone))
    service_name = booking.service.name if booking.service else "your appointment"
    return f"You're booked for {service_name} on {local_start.strftime('%a %b %d, %H:%M')}."
