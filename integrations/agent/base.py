from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AgentResponse:
    """The common language between any agent implementation (MockAgent now,
    the real LLM agent in a later sprint) and the rest of the pipeline, so
    the pipeline doesn't need to change when the mock is swapped out.

    Exactly one of two shapes:
    - A plain reply: action="reply", text set.
    - A tool call: action="tool_call", tool set to a registered tool name,
      tool_args holding whatever arguments that tool expects.

    Use the .reply()/.tool_call() constructors rather than the dataclass
    constructor directly, so callers can't set an inconsistent combination
    of fields.
    """

    action: Literal["reply", "tool_call"]
    text: str | None = None
    tool: str | None = None
    tool_args: dict = field(default_factory=dict)

    @classmethod
    def reply(cls, text):
        return cls(action="reply", text=text)

    @classmethod
    def tool_call(cls, tool, tool_args=None):
        return cls(action="tool_call", tool=tool, tool_args=tool_args or {})
