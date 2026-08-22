"""Agent adapters. Importing this package registers built-in adapters."""

from tooltrace.agents.base import AgentAdapter
from tooltrace.agents.openai_compat import OpenAICompatAgent
from tooltrace.agents.scripted import ScriptedAgent
from tooltrace.agents.subprocess import SubprocessAgent
from tooltrace.core.registry import agent_registry

agent_registry.register("scripted")(ScriptedAgent)
agent_registry.register("subprocess")(SubprocessAgent)
agent_registry.register("openai_compat")(OpenAICompatAgent)

__all__ = ["AgentAdapter", "OpenAICompatAgent", "ScriptedAgent", "SubprocessAgent"]
