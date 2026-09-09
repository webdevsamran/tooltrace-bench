"""Weighted composite scoring over deterministic assertions.

Two kinds of scorer are dispatched here. The original kind takes
`(params, workspace)` and reads the final state of the filesystem. The
second takes `(params, trace)` and reads the trajectory -- which tools were
called, with what arguments, in what order -- because a tool-call check is
inexpressible against a workspace alone.

The `trace` argument is optional and defaults to `None`, so every existing
caller keeps working unchanged and a task with no trace-aware assertions
scores exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from tooltrace.core.models import Score, TaskDefinition
from tooltrace.core.registry import scorer_registry
from tooltrace.scoring.trace_scorers import TRACE_SCORERS
from tooltrace.scoring.trace_view import TraceView


def score_task(
    task: TaskDefinition, workspace: Path, trace: TraceView | None = None
) -> tuple[Score, dict[str, str]]:
    """Run every assertion; return the composite Score plus per-assertion detail.

    Composite = weighted mean of component scores. Success requires every
    component to be 1.0.
    """
    components: dict[str, float] = {}
    weights: dict[str, float] = {}
    details: dict[str, str] = {}

    for i, assertion in enumerate(task.assertions):
        key = assertion.description or f"{assertion.type}#{i}"
        try:
            if assertion.type in TRACE_SCORERS:
                if trace is None:
                    # Refuse rather than score zero: "we could not look" and
                    # "we looked and it failed" are different facts, and a
                    # silent zero would read as the second.
                    components[key] = 0.0
                    details[key] = (
                        f"{assertion.type} needs the trajectory, which this caller did not supply"
                    )
                    weights[key] = assertion.weight
                    continue
                outcome = TRACE_SCORERS[assertion.type](assertion.params, trace)
            else:
                scorer = scorer_registry.get(assertion.type)
                outcome = scorer(assertion.params, workspace)
        except KeyError:
            components[key] = 0.0
            details[key] = f"unknown assertion type: {assertion.type}"
        except Exception as exc:
            components[key] = 0.0
            details[key] = f"scorer error: {type(exc).__name__}: {exc}"
        else:
            components[key] = max(0.0, min(1.0, outcome.score))
            details[key] = outcome.detail
        weights[key] = assertion.weight

    total_weight = sum(weights.values()) or 1.0
    total = sum(components[k] * weights[k] for k in components) / total_weight
    return (
        Score(total=round(total, 6), components=components, weights=weights),
        details,
    )


def is_success(score: Score) -> bool:
    return bool(score.components) and all(v == 1.0 for v in score.components.values())


def is_partial_success(score: Score) -> bool:
    return not is_success(score) and score.total >= 0.5
