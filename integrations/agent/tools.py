from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bookings.availability import TimeSlot, check_availability
from bookings.models import Service
from bookings.services import SlotUnavailableError, create_booking
from conversations.models import Conversation

# OpenAI-compatible function-calling schemas (OpenRouter's chat completions
# endpoint follows this shape regardless of the underlying model).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Look up open appointment slots for this business.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Name of the service, if the customer specified one.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": (
                "Book an appointment. Only call this once the customer has "
                "confirmed both a specific service and a specific date/time "
                "(normally one just offered by check_availability)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "The exact name of the service being booked.",
                    },
                    "start_time": {
                        "type": "string",
                        "description": (
                            "The appointment's start time as an ISO 8601 datetime, "
                            "e.g. 2026-09-04T09:00:00."
                        ),
                    },
                },
                "required": ["service_name", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "Ask the customer a clarifying question when required booking "
                "details (service, date, time) are still missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to send to the customer.",
                    },
                    "known_slots": {
                        "type": "object",
                        "description": (
                            "Booking details already confirmed in this conversation "
                            "so far (e.g. service, date, time) - whatever is known, "
                            "even if incomplete."
                        ),
                    },
                },
                "required": ["question"],
            },
        },
    },
]


def ask_clarification(text):
    """Pass-through: returns the given text unchanged.

    Exists so the tool-calling interface stays uniform - every agent
    action goes through a named tool, even a trivial one - rather than
    needing a special case for clarification questions in the pipeline.
    """
    return text


def _find_service(tenant, name):
    if not name:
        return None
    return Service.objects.filter(tenant=tenant, name__iexact=name, is_active=True).first()


def _check_availability_tool(tenant, conversation, tool_args):
    service = _find_service(tenant, tool_args.get("service"))
    return check_availability(tenant, service=service)


def _create_booking_tool(tenant, conversation, tool_args):
    service = _find_service(tenant, tool_args.get("service_name"))
    if service is None:
        return {
            "status": "error",
            "message": "I couldn't find that service - could you confirm its exact name?",
        }

    try:
        start = datetime.fromisoformat(tool_args.get("start_time") or "")
    except ValueError:
        return {
            "status": "error",
            "message": "I didn't understand that date/time - could you rephrase it?",
        }
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo(tenant.timezone))

    slot = TimeSlot(start=start, end=start + timedelta(minutes=service.duration_minutes))
    try:
        booking = create_booking(tenant, conversation.end_user, slot, service)
    except SlotUnavailableError:
        return {
            "status": "error",
            "message": "Sorry, that time was just taken - would you like to try another?",
        }

    conversation.status = Conversation.Status.ACTIVE
    conversation.pending_intent_state = {}
    conversation.save(update_fields=["status", "pending_intent_state"])
    return {"status": "confirmed", "booking": booking}


def _ask_clarification_tool(tenant, conversation, tool_args):
    conversation.status = Conversation.Status.AWAITING_USER
    conversation.pending_intent_state = tool_args.get("known_slots") or {}
    conversation.save(update_fields=["status", "pending_intent_state"])
    return ask_clarification(tool_args.get("question", ""))


# Adapts each tool's own literal signature to a uniform (tenant, conversation,
# tool_args) calling convention, so the pipeline can dispatch generically by
# name. create_booking needs conversation.end_user; ask_clarification and
# create_booking both use it to update conversation.status/pending_intent_state
# (multi-turn slot filling) - check_availability accepts and ignores it.
TOOL_REGISTRY = {
    "check_availability": _check_availability_tool,
    "create_booking": _create_booking_tool,
    "ask_clarification": _ask_clarification_tool,
}


def execute_tool(tool_name, tenant, conversation, tool_args):
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name!r}")
    return tool(tenant, conversation, tool_args)
