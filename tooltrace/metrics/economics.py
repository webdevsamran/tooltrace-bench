"""Cost per resolved task, and the cost-accuracy frontier.

"Which model is best" is the wrong question in production; "which model resolves
the most tasks per dollar" is the one teams actually decide on. The Holistic
Agent Leaderboard paper names this directly: agents vary widely in cost and
**evaluations rarely report it**.

This repository already had the pieces — `UsageMetadata.provider_cost_reported`,
`TokenUsage`, and a dated `PriceTable` — and no path that turned them into a
number a user sees. `benchmark` reported success rates and latency and never
mentioned money.

The honesty rule from `UsageMetadata` carries through unchanged, and it is the
reason this module is short: **cost appears only when a provider reported it, or
when an explicit dated price table prices the model.** Nothing here estimates,
interpolates, or falls back to a "typical" rate. A run whose adapter reports no
usage produces `null`, not `0.0`, and a summary says how many runs were priced
so a reader can see how much of the picture is missing.

`cost_per_resolved_task` is deliberately *not* mean cost. A run that fails cost
real money, and dividing total spend by successes is what a team's budget
actually experiences. The two differ sharply for an unreliable agent, which is
the entire point of measuring it.
"""

from __future__ import annotations

from typing import Any

#: What a summary reports when nothing was measured. Named so the intent is
#: unmistakable at every call site: this is "unknown", never "zero".
UNKNOWN: None = None


def _cost_of(result: dict[str, Any]) -> float | None:
    usage = result.get("usage") or {}
    if not isinstance(usage, dict):
        return UNKNOWN
    reported = usage.get("provider_cost_reported")
    return float(reported) if isinstance(reported, int | float) else UNKNOWN


def _tokens_of(result: dict[str, Any]) -> int | None:
    usage = result.get("usage") or {}
    tokens = usage.get("tokens") if isinstance(usage, dict) else None
    total = tokens.get("total_tokens") if isinstance(tokens, dict) else None
    return int(total) if isinstance(total, int) else UNKNOWN


def cost_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Spend for a set of runs, and what it bought.

    Every field is `None` when nothing was measured, and `priced_runs` says how
    many of the runs contributed, so a partial picture cannot be mistaken for a
    complete one.
    """
    costs = [c for c in (_cost_of(r) for r in results) if c is not None]
    tokens = [t for t in (_tokens_of(r) for r in results) if t is not None]
    resolved = sum(1 for r in results if r.get("success"))

    total_cost = round(sum(costs), 6) if costs else UNKNOWN
    currencies = {
        str((r.get("usage") or {}).get("currency"))
        for r in results
        if isinstance(r.get("usage"), dict) and (r.get("usage") or {}).get("currency")
    }

    return {
        "runs": len(results),
        "priced_runs": len(costs),
        "resolved_runs": resolved,
        "total_cost": total_cost,
        # The number a budget actually experiences: failed runs cost money too.
        "cost_per_resolved_task": (
            round(sum(costs) / resolved, 6) if costs and resolved else UNKNOWN
        ),
        "cost_per_run": round(sum(costs) / len(costs), 6) if costs else UNKNOWN,
        "total_tokens": sum(tokens) if tokens else UNKNOWN,
        "tokens_per_resolved_task": (
            round(sum(tokens) / resolved, 2) if tokens and resolved else UNKNOWN
        ),
        # More than one currency in one summary cannot be added up honestly.
        "currency": next(iter(currencies)) if len(currencies) == 1 else UNKNOWN,
        "mixed_currencies": len(currencies) > 1,
    }


def cost_accuracy_points(per_agent: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """One (cost, accuracy) point per agent, for a frontier plot."""
    points = []
    for agent, results in sorted(per_agent.items()):
        if not results:
            continue
        summary = cost_summary(results)
        rate = sum(1 for r in results if r.get("success")) / len(results)
        points.append(
            {
                "agent": agent,
                "success_rate": round(rate, 6),
                "cost_per_resolved_task": summary["cost_per_resolved_task"],
                "total_cost": summary["total_cost"],
                "priced_runs": summary["priced_runs"],
                "runs": summary["runs"],
            }
        )
    return points


def pareto_frontier(points: list[dict[str, Any]]) -> list[str]:
    """Agents no other agent beats on both accuracy and cost.

    A point is dominated when another is at least as accurate *and* at least as
    cheap, and strictly better on one of them. Points with no measured cost are
    excluded rather than treated as free — a frontier that silently ranks an
    unpriced agent as cheapest would be worse than no frontier.
    """
    priced = [p for p in points if p.get("cost_per_resolved_task") is not None]
    frontier = []
    for candidate in priced:
        dominated = any(
            other is not candidate
            and other["success_rate"] >= candidate["success_rate"]
            and other["cost_per_resolved_task"] <= candidate["cost_per_resolved_task"]
            and (
                other["success_rate"] > candidate["success_rate"]
                or other["cost_per_resolved_task"] < candidate["cost_per_resolved_task"]
            )
            for other in priced
        )
        if not dominated:
            frontier.append(str(candidate["agent"]))
    return sorted(frontier)
