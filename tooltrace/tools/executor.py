"""Tool executor: the single choke point through which every agent tool call
flows. Responsibilities:

- enforce the task's tool allowlist;
- time every call;
- apply deterministic perturbation hooks (fault injection);
- emit sanitized ``tool_request`` / ``tool_result`` trace events;
- track repeated/invalid/failed call statistics.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC
from typing import Any

from tooltrace.core.models import TraceEvent
from tooltrace.core.registry import tool_registry
from tooltrace.security.sanitize import sanitize_obj, summarize
from tooltrace.tools.base import ToolContext, ToolResult, summarize_args


class ExecutionStats:
    """Mutable counters for one run."""

    def __init__(self) -> None:
        self.tool_calls = 0
        self.failed_tool_calls = 0
        self.invalid_tool_calls = 0
        self.repeated_calls = 0
        self.tool_ms = 0.0
        self._last_signature: str | None = None


class ToolExecutor:
    def __init__(
        self,
        ctx: ToolContext,
        allowed_tools: list[str],
        emit_event: Callable[[TraceEvent], None],
        seq_start: int = 0,
        perturbation_hook: Callable[[str, dict[str, Any]], str | None] | None = None,
    ) -> None:
        """
        ``perturbation_hook(tool_name, args) -> error_message | None`` lets the
        runner inject controlled faults deterministically.
        """
        self.ctx = ctx
        self.allowed = set(allowed_tools)
        self.emit_event = emit_event
        self.seq = seq_start
        self.stats = ExecutionStats()
        self.perturbation_hook = perturbation_hook

    # -- internals ----------------------------------------------------------

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def _event(self, type_: str, payload: dict[str, Any]) -> TraceEvent:
        return TraceEvent(
            timestamp=_iso_now(),
            seq=self._next_seq(),
            type=type_,  # type: ignore[arg-type]
            payload=sanitize_obj(payload),  # type: ignore[arg-type]
        )

    # -- public API ---------------------------------------------------------

    def execute(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        args = args or {}
        self.stats.tool_calls += 1

        signature = json.dumps(
            [tool_name, sorted((k, repr(v)) for k, v in args.items())],
            sort_keys=True,
        )
        if signature == self.stats._last_signature:
            self.stats.repeated_calls += 1
        self.stats._last_signature = signature

        request_payload = {
            "tool": tool_name,
            "args_summary": summarize_args(args),
            # sanitized full args enable deterministic replay of tool calls
            "args": sanitize_obj(args),
        }
        self.emit_event(self._event("tool_request", request_payload))

        start = time.perf_counter()

        # Policy: unknown tool => hallucinated resource.
        if not tool_registry.has(tool_name):
            result = ToolResult(
                ok=False,
                error=f"unknown tool {tool_name!r} (not registered)",
                data={"invalid": True},
            )
        elif tool_name not in self.allowed:
            result = ToolResult(
                ok=False,
                error=f"tool {tool_name!r} not allowed by task policy",
                data={"denied": True},
            )
        else:
            injected_error = (
                self.perturbation_hook(tool_name, args) if self.perturbation_hook else None
            )
            if injected_error is not None:
                result = ToolResult(ok=False, error=injected_error, data={"injected": True})
            else:
                try:
                    tool_cls = tool_registry.get(tool_name)
                    tool = tool_cls() if isinstance(tool_cls, type) else tool_cls
                    tool.validate_args(args)
                    result = tool.run(args, self.ctx)
                except Exception as exc:
                    result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        duration_ms = (time.perf_counter() - start) * 1000.0
        self.stats.tool_ms += duration_ms
        if not result.ok:
            self.stats.failed_tool_calls += 1
        if result.data.get("invalid") or result.data.get("denied"):
            self.stats.invalid_tool_calls += 1

        status = "ok" if result.ok else ("denied" if result.data.get("denied") else "error")
        self.emit_event(
            self._event(
                "tool_result",
                {
                    "tool": tool_name,
                    "status": status,
                    "duration_ms": round(duration_ms, 3),
                    "result_summary": summarize(result.output, limit=300),
                    "error": summarize(result.error, limit=200) if result.error else None,
                    "data": sanitize_obj(result.data),
                },
            )
        )
        return result


def _iso_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
