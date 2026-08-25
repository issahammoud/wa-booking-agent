from integrations.agent.base import AgentResponse

# Deliberately simple - this exists to exercise the pipeline shape, not to
# be a good conversational experience. Resist making it smarter.
BOOKING_KEYWORDS = ("book", "appointment", "rendez-vous")
CANNED_REPLY = "Thanks for your message, how can I help?"


class MockAgent:
    """Rule-based stand-in for the real LLM agent (a later sprint)."""

    def respond(self, conversation, messages):
        combined_text = " ".join(m.content for m in messages if m.content).lower()
        if any(keyword in combined_text for keyword in BOOKING_KEYWORDS):
            return AgentResponse.tool_call("check_availability")
        return AgentResponse.reply(CANNED_REPLY)
