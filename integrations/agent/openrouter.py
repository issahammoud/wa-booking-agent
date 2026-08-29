import json
import logging

import requests
from django.conf import settings

from integrations.agent.base import AgentResponse
from integrations.agent.prompts import build_system_prompt
from integrations.agent.tools import TOOL_SCHEMAS

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

_ROLE_BY_DIRECTION = {"inbound": "user", "outbound": "assistant"}

FALLBACK_REPLY = "Sorry, I'm having trouble responding right now - please try again in a moment."


class OpenRouterAgent:
    """Real LLM-backed agent via OpenRouter's OpenAI-compatible chat completions API.

    `messages` (the newly-buffered batch) is accepted to match MockAgent's
    signature but not used directly - conversation.messages already includes
    those rows (persisted before this is called), and using the full history
    here is what lets multi-turn conversations continue naturally.
    """

    def respond(self, conversation, messages):
        history = [
            {"role": _ROLE_BY_DIRECTION[message.direction], "content": message.content}
            for message in conversation.messages.order_by("created_at")
            if message.content
        ]
        system_content = build_system_prompt(conversation.tenant)
        if conversation.pending_intent_state:
            system_content += (
                "\n\nBooking details already confirmed earlier in this conversation "
                f"(don't ask for these again unless something changed): "
                f"{json.dumps(conversation.pending_intent_state)}"
            )

        payload = {
            "model": settings.AGENT_MODEL,
            "messages": [{"role": "system", "content": system_content}, *history],
            "tools": TOOL_SCHEMAS,
        }
        headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}

        try:
            response = requests.post(OPENROUTER_CHAT_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            choice = response.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, IndexError, ValueError):
            logger.exception(
                "OpenRouter chat completion failed for tenant=%s", conversation.tenant_id
            )
            return AgentResponse.reply(FALLBACK_REPLY)

        tool_calls = choice.get("tool_calls")
        if tool_calls:
            function = tool_calls[0]["function"]
            try:
                tool_args = json.loads(function["arguments"])
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
            return AgentResponse.tool_call(function["name"], tool_args)

        return AgentResponse.reply(choice.get("content") or FALLBACK_REPLY)
