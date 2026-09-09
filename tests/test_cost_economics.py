"""Cost must be reported, and must never be invented.

Evaluations rarely report what a run cost — the Holistic Agent Leaderboard paper
names this as one of the field's standing gaps — and this repository had every
piece needed (`UsageMetadata.provider_cost_reported`, `TokenUsage`, a dated
`PriceTable`) with no path that turned them into a number a user sees.

The hard rule inherited from `UsageMetadata` is that cost appears only when a
provider reported it. Nothing estimates, interpolates or substitutes a typical
rate. That is what most of these tests are about: an unmeasured cost must stay
`None`, because a `0.0` here would read as "free" and quietly win a comparison.
"""

from __future__ import annotations

from typing import Any

import pytest
from tooltrace.metrics.economics import (
    cost_accuracy_points,
    cost_summary,
    pareto_frontier,
)
from tooltrace.runners.benchmark import run_benchmark
from tooltrace.tasks import load_all_tasks


def _run(
    success: bool, cost: float | None, tokens: int | None = None, currency: str = "USD"
) -> dict[str, Any]:
    usage: dict[str, Any] = {"currency": currency if cost is not None else None}
    if cost is not None:
        usage["provider_cost_reported"] = cost
    if tokens is not None:
        usage["tokens"] = {"total_tokens": tokens}
    return {"success": success, "usage": usage}


# --- honesty ---------------------------------------------------------------


def test_unpriced_runs_report_unknown_not_zero() -> None:
    """A `0.0` here reads as "free" and would win any comparison."""
    summary = cost_summary([_run(True, None), _run(True, None)])
    assert summary["total_cost"] is None
    assert summary["cost_per_resolved_task"] is None
    assert summary["priced_runs"] == 0
    assert summary["runs"] == 2


def test_a_partial_picture_says_how_partial_it_is() -> None:
    summary = cost_summary([_run(True, 0.10), _run(True, None), _run(True, None)])
    assert summary["priced_runs"] == 1
    assert summary["runs"] == 3
    assert summary["total_cost"] == 0.1


def test_mixed_currencies_are_flagged_rather_than_added_up() -> None:
    summary = cost_summary([_run(True, 1.0, currency="USD"), _run(True, 1.0, currency="EUR")])
    assert summary["mixed_currencies"] is True
    assert summary["currency"] is None


def test_a_single_currency_is_reported() -> None:
    summary = cost_summary([_run(True, 1.0), _run(True, 2.0)])
    assert summary["currency"] == "USD"
    assert summary["mixed_currencies"] is False


def test_no_resolved_runs_means_no_cost_per_resolved_task() -> None:
    """Dividing by zero successes is undefined, not infinite and not zero."""
    summary = cost_summary([_run(False, 5.0), _run(False, 5.0)])
    assert summary["total_cost"] == 10.0
    assert summary["cost_per_resolved_task"] is None


# --- the metric that matters ------------------------------------------------


def test_cost_per_resolved_task_counts_the_failures_too() -> None:
    """A failed run spent real money; a budget experiences total over successes."""
    results = [_run(True, 1.0), _run(False, 1.0), _run(False, 1.0), _run(True, 1.0)]
    summary = cost_summary(results)
    assert summary["total_cost"] == 4.0
    assert summary["cost_per_run"] == 1.0
    # Two successes for four dollars, not one dollar each.
    assert summary["cost_per_resolved_task"] == 2.0


def test_an_unreliable_agent_costs_more_per_resolved_task() -> None:
    reliable = cost_summary([_run(True, 1.0) for _ in range(4)])
    flaky = cost_summary([_run(i % 2 == 0, 1.0) for i in range(4)])
    assert reliable["cost_per_run"] == flaky["cost_per_run"] == 1.0
    assert flaky["cost_per_resolved_task"] > reliable["cost_per_resolved_task"]


def test_tokens_are_summarised_when_reported() -> None:
    summary = cost_summary([_run(True, 1.0, tokens=1000), _run(True, 1.0, tokens=500)])
    assert summary["total_tokens"] == 1500
    assert summary["tokens_per_resolved_task"] == 750.0


# --- frontier ---------------------------------------------------------------


def test_the_frontier_keeps_only_undominated_agents() -> None:
    points = cost_accuracy_points(
        {
            "cheap-and-good": [_run(True, 1.0)],
            "expensive-and-good": [_run(True, 10.0)],
            "cheap-and-bad": [_run(False, 1.0), _run(True, 1.0)],
        }
    )
    frontier = pareto_frontier(points)
    assert "cheap-and-good" in frontier
    assert "expensive-and-good" not in frontier, "same accuracy, ten times the cost"


def test_an_unpriced_agent_is_excluded_rather_than_treated_as_free() -> None:
    """Otherwise the cheapest agent on the frontier is the one nobody measured."""
    points = cost_accuracy_points({"priced": [_run(True, 5.0)], "unpriced": [_run(True, None)]})
    assert pareto_frontier(points) == ["priced"]


def test_a_more_accurate_agent_survives_a_higher_cost() -> None:
    points = cost_accuracy_points(
        {
            "accurate": [_run(True, 10.0), _run(True, 10.0)],
            "cheap": [_run(True, 1.0), _run(False, 1.0)],
        }
    )
    assert sorted(pareto_frontier(points)) == ["accurate", "cheap"]


@pytest.mark.parametrize("points", [[], [{"agent": "a", "success_rate": 1.0}]])
def test_a_frontier_over_nothing_priced_is_empty(points: list) -> None:
    assert pareto_frontier(points) == []


# --- wiring -----------------------------------------------------------------


def test_benchmark_reports_a_cost_block() -> None:
    task = next(t for t in load_all_tasks() if t.id == "file-editing/fix-config-typo")
    bench = run_benchmark([task], "scripted", runs=1)
    cost = bench.summary["overall"]["cost"]
    assert cost["runs"] == 1
    # The scripted agent reports no usage, so this must be unknown, not free.
    assert cost["priced_runs"] == 0
    assert cost["total_cost"] is None
    assert bench.summary["per_task"][task.id]["cost"]["runs"] == 1
