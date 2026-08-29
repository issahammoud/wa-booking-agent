from bookings.availability import check_availability


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
