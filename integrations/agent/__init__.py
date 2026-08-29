from django.conf import settings

from integrations.agent.mock import MockAgent
from integrations.agent.openrouter import OpenRouterAgent

_AGENTS = {
    "mock": MockAgent,
    "openrouter": OpenRouterAgent,
}


def get_agent():
    return _AGENTS[settings.AGENT_BACKEND]()
