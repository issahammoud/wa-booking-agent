from bookings.availability import check_availability

# OpenAI-compatible function-calling schemas (OpenRouter's chat completions
# endpoint follows this shape regardless of the underlying model). Sprint 8
# ticket 2 adds create_booking and refines these descriptions.
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
            "name": "ask_clarification",
            "description": (
                "Ask the customer a clarifying question when required booking "
                "details are missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The question to send to the customer.",
                    },
                },
                "required": ["text"],
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


def _check_availability_tool(tenant, tool_args):
    return check_availability(tenant, tool_args.get("date_range"), service=tool_args.get("service"))


def _ask_clarification_tool(tenant, tool_args):
    return ask_clarification(tool_args.get("text", ""))


# Adapts each tool's own literal signature to a uniform (tenant, tool_args)
# calling convention, so the pipeline can dispatch generically by name.
TOOL_REGISTRY = {
    "check_availability": _check_availability_tool,
    "ask_clarification": _ask_clarification_tool,
}


def execute_tool(tool_name, tenant, tool_args):
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name!r}")
    return tool(tenant, tool_args)
