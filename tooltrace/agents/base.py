"""Stable agent adapter API.

An adapter:

- ``initialize(ctx)``   — receives the task context once;
- ``act(step, obs)``    — returns the next :class:`AgentAction` given prior
                          tool observations (the runner owns the loop);
- ``finalize()``        — returns the final :class:`AgentOutcome` including
                          usage metadata and artifacts.

Adapters are discovered via the ``tooltrace.agents`` entry-point group.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tooltrace.core.models import AgentAction, AgentContext, AgentOutcome


class AgentAdapter(ABC):
    """Base class every agent adapter implements."""

    name: str = "agent"

    def __init__(self, config: dict[str, object] | None = None) -> None:
        self.config: dict[str, object] = dict(config or {})

    @abstractmethod
    def initialize(self, ctx: AgentContext) -> None:
        """Prepare the adapter for a new task run."""

    @abstractmethod
    def act(self, step: int, observations: list[str]) -> AgentAction:
        """Return the next action. ``observations`` holds one formatted string
        per prior tool result."""

    @abstractmethod
    def finalize(self) -> AgentOutcome:
        """Produce the final outcome after the loop ends."""
