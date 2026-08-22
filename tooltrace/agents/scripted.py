"""Scripted agent: deterministic tool-call replay.

Config:
    {"script": [{"tool": "write_file", "args": {...}}, ...],
     "final_message": "done"}

The scripted agent makes CI, tests and examples fully reproducible without
any model. It is a real adapter — runs go through the same executor, trace
and scoring pipeline as model-backed agents.
"""

from __future__ import annotations

from tooltrace.agents.base import AgentAdapter
from tooltrace.core.models import AgentAction, AgentContext, AgentOutcome, UsageMetadata


class ScriptedAgent(AgentAdapter):
    name = "scripted"

    def initialize(self, ctx: AgentContext) -> None:
        script = self.config.get("script", [])
        if not isinstance(script, list):
            raise ValueError("scripted agent config 'script' must be a list")
        self._script: list[dict[str, object]] = list(script)
        self._index = 0
        self._messages: list[str] = []
        self._ctx = ctx

    def act(self, step: int, observations: list[str]) -> AgentAction:
        if self._index >= len(self._script):
            return AgentAction(kind="finish", message="script complete")
        entry = self._script[self._index]
        self._index += 1
        tool = entry.get("tool")
        args = entry.get("args", {})
        if not isinstance(tool, str) or not isinstance(args, dict):
            return AgentAction(
                kind="finish",
                finish_reason="error",  # type: ignore[arg-type]
                message="malformed script entry",
            )
        return AgentAction(kind="tool", tool=tool, args=args)

    def finalize(self) -> AgentOutcome:
        return AgentOutcome(
            messages=self._messages,
            final_output=str(self.config.get("final_message", "script complete")),
            finish_reason="finished",
            usage=UsageMetadata(),  # scripted agents consume no model tokens
        )
