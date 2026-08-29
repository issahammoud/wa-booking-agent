def build_system_prompt(tenant):
    """Minimal first-pass system prompt - proves the OpenRouter wiring works.

    Sprint 8 ticket 2 replaces this with real tone/language/tool-choice
    guidance and tenant.system_prompt_overrides support.
    """
    return (
        f"You are a booking assistant for {tenant.business_name}, "
        f"a {tenant.get_vertical_display().lower()} business. Help customers "
        "check availability and answer questions about booking an appointment."
    )
