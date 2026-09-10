"""Agent adapters. Importing this package registers built-in adapters."""

from tooltrace.agents.anthropic import AnthropicAgent
from tooltrace.agents.base import AgentAdapter
from tooltrace.agents.gemini import GeminiAgent
from tooltrace.agents.openai_compat import OpenAICompatAgent
from tooltrace.agents.scripted import ScriptedAgent
from tooltrace.agents.subprocess import SubprocessAgent
from tooltrace.core.registry import agent_registry

agent_registry.register("scripted")(ScriptedAgent)
agent_registry.register("subprocess")(SubprocessAgent)
agent_registry.register("openai_compat")(OpenAICompatAgent)
# Native adapters rather than presets, because neither API is reachable through
# `openai_compat`: Anthropic puts the system prompt at the top level and
# requires `max_tokens`, Gemini spells the assistant role `model` and wraps
# every turn in `parts`. A preset that posted the same body to a different path
# would fail on the first request.
agent_registry.register("anthropic")(AnthropicAgent)
agent_registry.register("gemini")(GeminiAgent)

__all__ = [
    "AgentAdapter",
    "AnthropicAgent",
    "GeminiAgent",
    "OpenAICompatAgent",
    "ScriptedAgent",
    "SubprocessAgent",
]
