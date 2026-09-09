"""Export a run as OpenTelemetry GenAI spans.

`tooltrace ingest` has always been able to read OTel GenAI spans. Nothing could
write them, so results ended here: a bundle you could inspect with this
project's own tools and nothing else. Meanwhile Langfuse, Phoenix, Datadog and
every other OTel backend speak exactly this format, and the GenAI semantic
conventions define agent, workflow, tool and model spans plus latency and token
metrics.

Being the harness that *feeds* those platforms is a better position than
competing with them, and this is the direction that makes it possible.

Two deliberate choices:

- **Spans are emitted as plain dicts in the OTLP JSON shape, not through the
  OpenTelemetry SDK.** Adding an SDK dependency to a supply-chain-audited,
  offline-first project — for a format that is a documented attribute
  vocabulary — is a poor trade. A dict round-trips through `from_otel_spans`,
  which is what the tests assert.
- **Nothing is transmitted.** This produces spans; sending them is the caller's
  decision, made with the caller's collector and the caller's network policy.
  A benchmark that phones home by default would be the wrong artifact entirely,
  and `docs/differentiators.md` promises it does not.

The conventions are still marked experimental upstream, so
`GENAI_CONVENTIONS_VERSION` records which revision these attribute names follow.
An exporter that silently tracked a moving spec would produce data nobody could
date.
"""

from __future__ import annotations

import json
from typing import Any

from tooltrace.core.models import EvalResult, TraceEvent

#: The semantic-convention revision these attribute names follow. Recorded on
#: every span so a consumer can tell what vocabulary it is reading.
GENAI_CONVENTIONS_VERSION = "1.41"

#: Nanoseconds. OTLP timestamps are integers since the epoch; a run's wall clock
#: is milliseconds, so the conversion happens in exactly one place.
_MS_TO_NS = 1_000_000

_SPAN_KIND_INTERNAL = 1


def _span(
    name: str,
    *,
    span_id: str,
    parent_id: str | None,
    start_ns: int,
    end_ns: int,
    attributes: dict[str, Any],
    status_ok: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "spanId": span_id,
        "parentSpanId": parent_id,
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "status": {"code": 1 if status_ok else 2},
        "attributes": {
            "gen_ai.conventions.version": GENAI_CONVENTIONS_VERSION,
            **{k: v for k, v in attributes.items() if v is not None},
        },
    }


def _tool_spans(events: list[TraceEvent], parent_id: str, base_ns: int) -> list[dict[str, Any]]:
    """One span per completed tool call, in `execute_tool` form."""
    spans: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    cursor_ns = base_ns

    for event in events:
        payload = dict(event.payload or {})
        if event.type == "tool_request":
            pending = {"seq": event.seq, "tool": payload.get("tool"), "args": payload.get("args")}
        elif event.type == "tool_result" and pending is not None:
            duration_ms = payload.get("duration_ms")
            duration_ns = int(float(duration_ms) * _MS_TO_NS) if duration_ms else 0
            status = str(payload.get("status") or "ok")
            spans.append(
                _span(
                    f"execute_tool {pending['tool']}",
                    span_id=f"tool-{pending['seq']}",
                    parent_id=parent_id,
                    start_ns=cursor_ns,
                    end_ns=cursor_ns + duration_ns,
                    status_ok=status == "ok",
                    attributes={
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": pending["tool"],
                        "gen_ai.tool.call.id": str(pending["seq"]),
                        "gen_ai.tool.call.arguments": json.dumps(
                            pending["args"] or {}, sort_keys=True, default=str
                        ),
                        # Present only when the call succeeded: `from_otel_spans`
                        # derives status from this attribute's presence, so
                        # emitting it on a failure would round-trip as a pass.
                        "gen_ai.tool.call.result": (
                            str(payload.get("result_summary") or "") if status == "ok" else None
                        ),
                        "error.type": None if status == "ok" else status,
                    },
                )
            )
            cursor_ns += max(duration_ns, 1)
            pending = None
    return spans


def result_to_otel_spans(result: EvalResult, events: list[TraceEvent]) -> list[dict[str, Any]]:
    """One run as an OTel GenAI span tree: an agent span with tool children."""
    root_id = f"run-{result.run_id}"
    base_ns = 0
    total_ns = int((result.wall_ms or 0) * _MS_TO_NS)

    tokens = (result.usage.tokens if result.usage else None) if result.usage else None
    root = _span(
        f"invoke_agent {result.agent}",
        span_id=root_id,
        parent_id=None,
        start_ns=base_ns,
        end_ns=base_ns + total_ns,
        status_ok=bool(result.success),
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": result.agent,
            "gen_ai.conversation.id": result.run_id,
            # Unmeasured stays absent rather than zero: `_span` drops None, so a
            # consumer sees "not reported" instead of a fabricated 0 tokens.
            "gen_ai.usage.input_tokens": tokens.prompt_tokens if tokens else None,
            "gen_ai.usage.output_tokens": tokens.completion_tokens if tokens else None,
            # tooltrace-specific facts, namespaced so they cannot collide with
            # the GenAI vocabulary.
            "tooltrace.task.id": result.task_id,
            "tooltrace.task.version": result.task_version,
            "tooltrace.score.total": result.score.total,
            "tooltrace.success": result.success,
            "tooltrace.failure_reason": result.failure_reason.value
            if result.failure_reason
            else None,
            "tooltrace.steps": result.steps,
            "tooltrace.tool_calls": result.tool_calls,
            "tooltrace.framework_version": result.framework_version,
        },
    )
    return [root, *_tool_spans(events, root_id, base_ns)]


def to_otlp_json(
    spans: list[dict[str, Any]], *, service_name: str = "tooltrace-bench"
) -> dict[str, Any]:
    """Wrap spans in the OTLP `resourceSpans` envelope a collector accepts."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": {
                        "service.name": service_name,
                        "telemetry.sdk.name": "tooltrace-bench",
                    }
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "tooltrace.exporters.otel",
                            "version": GENAI_CONVENTIONS_VERSION,
                        },
                        "spans": spans,
                    }
                ],
            }
        ]
    }
