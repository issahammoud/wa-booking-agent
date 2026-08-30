from zoneinfo import ZoneInfo

from django.utils import timezone

_DAY_LABELS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}


def build_system_prompt(tenant):
    """Real system prompt (Sprint 8 ticket 2).

    Explicitly states working hours so the model doesn't guess/hallucinate
    them (observed during ticket 1's live verification), and gives explicit
    tool-choice guidance so it doesn't call a tool - or skip one - by luck.
    Also states today's date (Sprint 9 ticket 3) - without it, a relative or
    partial date like "September 1st" gets resolved against the model's own
    training-data assumptions rather than reality, which produced a real
    wrong-year booking during live testing.
    """
    today = timezone.now().astimezone(ZoneInfo(tenant.timezone))
    lines = [
        f"You are the booking assistant for {tenant.business_name}, "
        f"a {tenant.get_vertical_display().lower()} business.",
        f"Today's date is {today.strftime('%Y-%m-%d')} ({today.strftime('%A')}), "
        f"in {tenant.timezone}. Always resolve relative or partial dates the "
        'customer gives (e.g. "tomorrow", "next Monday", "September 1st") '
        "against this, never against your own assumptions.",
        "Be warm, concise, and professional. Always reply in the same "
        "language the customer just wrote in" + _language_hint(tenant) + ".",
        _working_hours_summary(tenant),
        "Tools:",
        "- Call check_availability when the customer wants to see open appointment times.",
        "- Call create_booking only once you know both the exact service and a "
        "specific date/time the customer has confirmed.",
        "- Call ask_clarification when you need more information before you can "
        "check availability or book (e.g. which service, which day/time) - never guess.",
        "- For anything else (general questions, greetings), just reply normally "
        "without calling a tool.",
        "- If you say you will check or look something up, call the matching tool "
        "in that same turn - never say you'll check without actually calling it.",
        "- check_availability only ever shows a few of the soonest open slots. If "
        "the customer rejects all of them or asks for something later, call "
        "check_availability again with after_date set to the last date you just "
        "offered - never claim nothing is available further out without actually "
        "checking first.",
    ]

    extra_instructions = tenant.system_prompt_overrides.get("extra_instructions")
    if extra_instructions:
        lines.append(extra_instructions)

    return "\n".join(lines)


def _language_hint(tenant):
    if not tenant.language_defaults:
        return ""
    return f" (this business typically serves customers in: {', '.join(tenant.language_defaults)})"


def _working_hours_summary(tenant):
    if not tenant.working_hours:
        return (
            "Working hours are not yet configured for this business - if asked, "
            "say you'll confirm hours separately rather than guessing."
        )
    parts = [
        f"{_DAY_LABELS.get(day, day)} {hours[0]}-{hours[1]}"
        for day, hours in tenant.working_hours.items()
    ]
    return f"Working hours: {', '.join(parts)} ({tenant.timezone})."
