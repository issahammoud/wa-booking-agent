import json
import logging

import requests
from django.conf import settings

from integrations.agent.base import AgentResponse
from integrations.agent.prompts import build_system_prompt
from integrations.agent.tools import TOOL_SCHEMAS, execute_tool, serialize_tool_result

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

    Unlike MockAgent, this agent owns the full round trip when a tool is
    called: it executes the tool itself and makes a second call feeding the
    result back, so the *model* phrases the final reply (in the customer's
    own language) instead of a Python string template. The pipeline
    (conversations/tasks.py) always just gets text back - action is always
    "reply" from this agent, never "tool_call".
    """

    def respond(self, conversation, messages):
        tenant = conversation.tenant
        base_messages = [
            {"role": "system", "content": self._system_content(conversation)},
            *self._history(conversation),
        ]

        choice = self._chat_completion(base_messages, tenant, tools=TOOL_SCHEMAS)
        if choice is None:
            return AgentResponse.reply(FALLBACK_REPLY)

        tool_calls = choice.get("tool_calls")
        if not tool_calls:
            return AgentResponse.reply(choice.get("content") or FALLBACK_REPLY)

        return self._respond_to_tool_call(
            base_messages, choice, tool_calls[0], tenant, conversation
        )

    def _respond_to_tool_call(self, base_messages, choice, call, tenant, conversation):
        function = call["function"]
        try:
            tool_args = json.loads(function["arguments"])
        except (json.JSONDecodeError, TypeError):
            tool_args = {}

        try:
            tool_result = execute_tool(function["name"], tenant, conversation, tool_args)
        except ValueError:
            logger.exception("Agent called unknown tool=%s", function["name"])
            return AgentResponse.reply(FALLBACK_REPLY)

        follow_up_messages = [
            *base_messages,
            {
                "role": "assistant",
                "content": choice.get("content"),
                "tool_calls": [call],
            },
            {
                "role": "tool",
                "tool_call_id": call.get("id", "call_1"),
                "content": serialize_tool_result(function["name"], tool_result, tenant),
            },
        ]
        final_choice = self._chat_completion(follow_up_messages, tenant, tools=None)
        if final_choice is None:
            return AgentResponse.reply(FALLBACK_REPLY)
        return AgentResponse.reply(final_choice.get("content") or FALLBACK_REPLY)

    def _history(self, conversation):
        return [
            {"role": _ROLE_BY_DIRECTION[message.direction], "content": message.content}
            for message in conversation.messages.order_by("created_at")
            if message.content
        ]

    def _system_content(self, conversation):
        content = build_system_prompt(conversation.tenant)
        if conversation.pending_intent_state:
            content += (
                "\n\nBooking details already confirmed earlier in this conversation "
                f"(don't ask for these again unless something changed): "
                f"{json.dumps(conversation.pending_intent_state)}"
            )
        return content

    def _chat_completion(self, messages, tenant, tools):
        payload = {"model": settings.AGENT_MODEL, "messages": messages}
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}

        try:
            response = requests.post(OPENROUTER_CHAT_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, IndexError, ValueError):
            logger.exception("OpenRouter chat completion failed for tenant=%s", tenant.id)
            return None
