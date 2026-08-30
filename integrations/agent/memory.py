WINDOW_SIZE = 30

# Only re-summarize once this many messages have aged out of the window
# since the last summary - bounds how often the extra LLM call runs,
# accepting a small gap (up to this many messages) that's in neither the
# verbatim window nor the summary yet.
SUMMARY_BATCH_SIZE = 10

_ROLE_LABEL = {"inbound": "Customer", "outbound": "Assistant"}


def windowed_messages(conversation):
    """The most recent WINDOW_SIZE messages with real content, oldest first -
    what the agent sends verbatim on every call, regardless of how long the
    conversation has actually run."""
    recent = conversation.messages.exclude(content="").order_by("-created_at")[:WINDOW_SIZE]
    return list(recent)[::-1]


def pending_summary_messages(conversation):
    """Messages that have fallen out of the window but aren't folded into
    context_summary yet, oldest first - empty until there are at least
    SUMMARY_BATCH_SIZE of them."""
    window_ids = {message.id for message in windowed_messages(conversation)}
    through_id = conversation.context_summary_through_message_id or 0
    older = list(
        conversation.messages.exclude(content="")
        .exclude(id__in=window_ids)
        .filter(id__gt=through_id)
        .order_by("created_at")
    )
    if len(older) < SUMMARY_BATCH_SIZE:
        return []
    return older


def build_summarization_prompt(conversation, new_messages):
    parts = []
    if conversation.context_summary:
        parts.append(f"Existing summary of earlier conversation:\n{conversation.context_summary}")
    transcript = "\n".join(
        f"{_ROLE_LABEL.get(message.direction, message.direction)}: {message.content}"
        for message in new_messages
    )
    parts.append(f"New messages to fold into the summary:\n{transcript}")
    parts.append(
        "Write a short (2-4 sentence) updated summary capturing any booking-"
        "relevant facts (service, dates/times discussed, preferences, "
        "decisions made) - a summary for your own future reference, not a "
        "reply to the customer and not a transcript."
    )
    return "\n\n".join(parts)


def persist_summary(conversation, summary_text, through_message_id):
    conversation.context_summary = summary_text
    conversation.context_summary_through_message_id = through_message_id
    conversation.save(update_fields=["context_summary", "context_summary_through_message_id"])
