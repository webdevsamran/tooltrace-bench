"""Converters from external trace formats to ToolTrace TraceEvent streams."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from tooltrace.core.models import TraceEvent

_TS = "1970-01-01T00:00:00+00:00"

# OTel GenAI attribute keys (semantic conventions, gen-* namespace)
_ATTR_TOOL = "gen_ai.tool.name"
_ATTR_TOOL_ARGS = "gen_ai.tool.call.arguments"
_ATTR_TOOL_RESULT = "gen_ai.tool.call.result"
_ATTR_MODEL = "gen_ai.request.model"
_ATTR_SYSTEM = "gen_ai.system"


def _ev(seq: int, type_: str, payload: dict[str, Any]) -> TraceEvent:
    return TraceEvent(timestamp=_TS, seq=seq, type=type_, payload=payload)  # type: ignore[arg-type]


def _coerce_args(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as dicts or JSON strings; never invent content."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw[:2000]}
        return decoded if isinstance(decoded, dict) else {"value": decoded}
    return {}


def from_otel_spans(
    spans: Iterable[Mapping[str, Any]],
    *,
    task_id: str = "ingested/external",
    agent: str | None = None,
) -> list[TraceEvent]:
    """Convert OTel GenAI span dicts into a ToolTrace event stream.

    Recognized span shapes:
    - tool-call spans: attribute ``gen_ai.tool.name`` present → emits a
      ``tool_request``/``tool_result`` pair (result status derived from the
      ``gen_ai.tool.call.result`` attribute being present).
    - model-call spans: attributes ``gen_ai.request.model`` / ``gen_ai.system``
      → emits an ``agent_message`` summary.
    - anything else → an ``agent_message`` with the span name.
    """
    detected_agent = agent
    events: list[TraceEvent] = [_ev(1, "task_start", {"task_id": task_id, "source": "otel-spans"})]
    seq = 1
    for span in spans:
        attrs = dict(span.get("attributes") or {})
        name = str(span.get("name", "span"))
        if detected_agent is None:
            system = attrs.get(_ATTR_SYSTEM)
            if isinstance(system, str) and system:
                detected_agent = system

        if _ATTR_TOOL in attrs:
            tool = str(attrs[_ATTR_TOOL])
            args = _coerce_args(attrs.get(_ATTR_TOOL_ARGS))
            result = attrs.get(_ATTR_TOOL_RESULT)
            seq += 1
            events.append(_ev(seq, "tool_request", {"tool": tool, "args": args}))
            seq += 1
            payload: dict[str, Any] = (
                {"tool": tool, "status": "ok", "summary": str(result)[:2000]}
                if result is not None
                else {"tool": tool, "status": "error", "error": "no result recorded"}
            )
            events.append(_ev(seq, "tool_result", payload))
        elif _ATTR_MODEL in attrs or name.startswith(("chat ", "gen_ai")):
            seq += 1
            events.append(
                _ev(
                    seq,
                    "agent_message",
                    {
                        "model": attrs.get(_ATTR_MODEL),
                        "span": name,
                        "summary": str(span.get("summary") or name)[:2000],
                    },
                )
            )
        else:
            seq += 1
            events.append(_ev(seq, "agent_message", {"span": name}))

    seq += 1
    events.append(
        _ev(seq, "task_end", {"finish_reason": "finished", "agent": detected_agent or "unknown"})
    )
    return events


def from_openai_steps(
    steps: Iterable[Mapping[str, Any]],
    *,
    task_id: str = "ingested/external",
    agent: str = "openai-compat",
) -> list[TraceEvent]:
    """Convert assistant-step records (OpenAI chat log shape) into events.

    Each step: ``{"content": str | None, "tool_calls":
    [{"name"|"function.name": ..., "arguments": dict | json-str}]}``.
    """
    events: list[TraceEvent] = [
        _ev(1, "task_start", {"task_id": task_id, "source": "openai-steps"})
    ]
    seq = 1
    for step in steps:
        content = step.get("content")
        if isinstance(content, str) and content.strip():
            seq += 1
            events.append(_ev(seq, "agent_message", {"text": content[:2000]}))
        for call in step.get("tool_calls") or []:
            if not isinstance(call, Mapping):
                continue
            raw_fn = call.get("function")
            fn: Mapping[str, Any] = raw_fn if isinstance(raw_fn, Mapping) else call
            name = fn.get("name")
            if not isinstance(name, str):
                continue
            args = _coerce_args(fn.get("arguments"))
            seq += 1
            events.append(_ev(seq, "tool_request", {"tool": name, "args": args}))
        for res in step.get("tool_results") or []:
            if not isinstance(res, Mapping):
                continue
            tool = str(res.get("tool", ""))
            ok = not res.get("error")
            seq += 1
            events.append(
                _ev(
                    seq,
                    "tool_result",
                    {
                        "tool": tool,
                        "status": "ok" if ok else "error",
                        **({} if ok else {"error": str(res.get("error"))[:2000]}),
                    },
                )
            )

    seq += 1
    events.append(_ev(seq, "task_end", {"finish_reason": "finished", "agent": agent}))
    return events


def format_counts(events: list[TraceEvent]) -> dict[str, int]:
    """Event-type histogram for quick ingest summaries."""
    counts: dict[str, int] = {}
    for e in events:
        counts[e.type] = counts.get(e.type, 0) + 1
    return counts
