"""Weighted composite scoring over deterministic assertions."""

from __future__ import annotations

from pathlib import Path

from tooltrace.core.models import Score, TaskDefinition
from tooltrace.core.registry import scorer_registry


def score_task(task: TaskDefinition, workspace: Path) -> tuple[Score, dict[str, str]]:
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
