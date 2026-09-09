"""A read-only view of a run's trajectory, for scorers that need to see it.

Every scorer in this project takes `(params, workspace)` and reads the final
state of the filesystem. That is the right default — it is what makes a score
reproducible from a bundle — but it means an entire class of question is
inexpressible: *how* did the agent get there? Which tools did it call, with
what arguments, in what order?

A tool-call scorer cannot be written against `(params, workspace)` at all, which
is why this project has fifteen scorers and none of them looks at a trajectory.

`TraceView` is the second argument such a scorer needs. It is deliberately
read-only and derived: it holds no reference to a live run, so a scorer written
against it works identically on a finished `.tooltrace` bundle as on a run in
progress. That is what keeps third-party verification possible — someone with
only the bundle can recompute the same number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tooltrace.core.models import TraceEvent


@dataclass(frozen=True)
class ToolCall:
    """One tool call: the request and the outcome that answered it."""

    seq: int
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None
    duration_ms: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class TraceView:
    """Everything a trace-aware scorer may read, and nothing it may change."""

    calls: tuple[ToolCall, ...] = ()
    events: tuple[TraceEvent, ...] = ()

    @classmethod
    def from_events(cls, events: list[TraceEvent]) -> TraceView:
        """Pair each `tool_request` with the `tool_result` that follows it.

        An unanswered request is dropped rather than given a fabricated
        outcome: a truncated trace must not be scored as though the last call
        succeeded.
        """
        calls: list[ToolCall] = []
        pending: dict[str, Any] | None = None
        for event in events:
            payload = dict(event.payload or {})
            if event.type == "tool_request":
                pending = {
                    "seq": event.seq or 0,
                    "tool": str(payload.get("tool") or ""),
                    "args": dict(payload.get("args") or {}),
                }
            elif event.type == "tool_result" and pending is not None:
                calls.append(
                    ToolCall(
                        seq=int(pending["seq"]),
                        tool=str(pending["tool"]),
                        args=dict(pending["args"]),
                        status=str(payload.get("status") or "ok"),
                        error=payload.get("error"),
                        duration_ms=payload.get("duration_ms"),
                    )
                )
                pending = None
        return cls(calls=tuple(calls), events=tuple(events))

    # -- convenience readers -------------------------------------------------

    def tools_used(self) -> list[str]:
        """Tool names in call order, including repeats."""
        return [c.tool for c in self.calls]

    def calls_to(self, tool: str) -> list[ToolCall]:
        return [c for c in self.calls if c.tool == tool]

    def succeeded_calls(self) -> list[ToolCall]:
        return [c for c in self.calls if c.ok]
