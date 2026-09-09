"""Turn a run's trace into the trajectory metrics, and aggregate across runs.

`tooltrace/metrics/` shipped ten functions — trajectory efficiency, loop
detection, hallucinated resources, context retention, tool-selection confusion,
verification quality, failure taxonomy, policy compliance, side-effect
correctness, change minimality — and **not one of them had a caller outside the
test suite**. No runner, CLI command, report, bundle field or web page ever
computed them, so a user running `tooltrace benchmark` received none of these
numbers. The package docstring still says "(Prompt-2 features 31-46)", which is
the tell: they were written against a feature list rather than a run path.

This module is the missing wiring. It exists because those functions each take
a different shape — some want paired tool events, some want a result dict, one
wants a diff summary — and something has to do that assembly once, in one
place, rather than at every call site.

Two deliberate constraints:

- **Nothing here touches `EvalResult` or the bundle layout.** Those are marked
  do-not-touch in AGENTS.md. The metrics land in `BenchmarkRun.summary`, which
  is an unversioned dict, so no artifact format changes and no committed bundle
  becomes incomparable.
- **An unmeasured quantity stays `None`.** The underlying functions already
  return `None` rather than `0` for unknowns, and the aggregation preserves
  that: a mean over zero measured values is `None`, never `0.0`.
"""

from __future__ import annotations

from statistics import fmean
from typing import Any

from tooltrace.core.models import EvalResult, TaskDefinition, TraceEvent
from tooltrace.metrics.policy import policy_compliance
from tooltrace.metrics.trajectory import (
    efficiency_metrics,
    failure_taxonomy_counts,
    hallucinated_resources,
    loop_detection,
    verification_quality,
)


def tool_events_from_trace(events: list[TraceEvent]) -> list[dict[str, Any]]:
    """Pair each `tool_request` with the `tool_result` that follows it.

    The metrics functions expect one record per tool call carrying both the
    request side (tool, args) and the outcome (status, error, summary). The
    trace stores those as two events, so nothing could consume them directly —
    which is part of why nothing did.
    """
    paired: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for event in events:
        payload = dict(event.payload or {})
        if event.type == "tool_request":
            pending = {
                "seq": event.seq,
                "tool": payload.get("tool"),
                "args_summary": payload.get("args_summary"),
                "args": payload.get("args"),
            }
        elif event.type == "tool_result" and pending is not None:
            pending.update(
                {
                    "status": payload.get("status"),
                    "duration_ms": payload.get("duration_ms"),
                    "result_summary": payload.get("result_summary"),
                    "error": payload.get("error"),
                }
            )
            paired.append(pending)
            pending = None
    return paired


def trajectory_report(
    result: EvalResult, events: list[TraceEvent], task: TaskDefinition
) -> dict[str, Any]:
    """Every per-run trajectory metric, computed from the run's own trace."""
    tool_events = tool_events_from_trace(events)
    result_dict = result.model_dump(mode="json")
    declared_side_effects = [str(s) for s in (task.metadata.get("side_effects") or [])]

    return {
        "efficiency": efficiency_metrics(result_dict),
        "loop": loop_detection(tool_events),
        "hallucinated_resources": hallucinated_resources(tool_events),
        # verification_quality reads `tool`/`status` at the top level but also
        # looks for a nested `payload.success` on task_end, so it needs both the
        # flattened payload and the payload itself.
        "verification": verification_quality(
            [
                {"type": e.type, "payload": dict(e.payload or {}), **dict(e.payload or {})}
                for e in events
            ]
        ),
        "policy": policy_compliance(tool_events, task.allowed_tools, declared_side_effects),
    }


def _mean_or_none(values: list[float]) -> float | None:
    """A mean over nothing is unknown, not zero."""
    return round(fmean(values), 6) if values else None


def aggregate_trajectory(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-run trajectory reports into one block for a summary."""
    if not reports:
        return {}

    efficiency_keys = sorted({k for r in reports for k in (r.get("efficiency") or {})})
    efficiency: dict[str, float | None] = {}
    for key in efficiency_keys:
        measured = [
            float(r["efficiency"][key])
            for r in reports
            if isinstance((r.get("efficiency") or {}).get(key), int | float)
        ]
        efficiency[key] = _mean_or_none(measured)

    stagnating = sum(1 for r in reports if (r.get("loop") or {}).get("is_stagnating"))
    hallucinations = sum(
        int((r.get("hallucinated_resources") or {}).get("count", 0)) for r in reports
    )
    non_compliant = sum(1 for r in reports if not (r.get("policy") or {}).get("compliant", True))
    unverified = [
        r
        for r in reports
        if (r.get("verification") or {}).get("claimed_success_without_verification")
    ]

    return {
        "runs": len(reports),
        "efficiency_mean": efficiency,
        "stagnating_runs": stagnating,
        "hallucinated_resource_events": hallucinations,
        "policy_violating_runs": non_compliant,
        "unverified_success_runs": len(unverified),
    }


def failure_taxonomy(results: list[EvalResult]) -> dict[str, int]:
    """Counts per failure class, so a summary says *how* runs failed."""
    counts = failure_taxonomy_counts([r.model_dump(mode="json") for r in results])
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
