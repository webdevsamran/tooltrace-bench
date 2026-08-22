"""Reliability statistics over repeated runs.

All functions are pure and deterministic given their inputs.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0, 100])."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    frac = rank - lower
    return ordered[lower] * (1 - frac) + ordered[upper] * frac


def p50(values: Sequence[float]) -> float:
    return percentile(values, 50)


def p95(values: Sequence[float]) -> float:
    return percentile(values, 95)


def success_rate(successes: Sequence[bool]) -> float:
    return sum(1 for s in successes if s) / len(successes) if successes else 0.0


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if total == 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    spread = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def consistency(successes: Sequence[bool]) -> dict[str, float]:
    """Success rate with a Wilson 95% confidence interval."""
    n = len(successes)
    k = sum(1 for s in successes if s)
    low, high = wilson_interval(k, n)
    return {"rate": success_rate(successes), "ci_low": low, "ci_high": high, "n": n}


def recovery_rate(recovery_opportunities: int, recoveries: int) -> float | None:
    """Fraction of injected faults after which the agent still completed."""
    if recovery_opportunities <= 0:
        return None
    return recoveries / recovery_opportunities


def summarize_reliability(results: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate reliability metrics from per-run result dicts.

    Expected keys per result: success (bool), partial_success (bool), steps,
    tool_calls, failed_tool_calls, wall_ms, recovered (bool|None).
    """
    if not results:
        return {}
    successes = [bool(r.get("success")) for r in results]
    partials = [bool(r.get("partial_success")) for r in results]
    steps = [float(r["steps"]) for r in results if isinstance(r.get("steps"), (int, float))]
    tool_calls = [
        float(r["tool_calls"]) for r in results if isinstance(r.get("tool_calls"), (int, float))
    ]
    failed_calls = [
        float(r["failed_tool_calls"])
        for r in results
        if isinstance(r.get("failed_tool_calls"), (int, float))
    ]
    wall = [float(r["wall_ms"]) for r in results if isinstance(r.get("wall_ms"), (int, float))]
    opportunities = sum(1 for r in results if r.get("recovered") is not None)
    recoveries = sum(1 for r in results if r.get("recovered"))
    out: dict[str, object] = {
        "runs": len(results),
        **consistency(successes),
        "partial_success_rate": success_rate(partials),
        "steps_mean": round(mean(steps), 3),
        "steps_p95": round(p95(steps), 3),
        "tool_calls_mean": round(mean(tool_calls), 3),
        "failed_tool_calls_mean": round(mean(failed_calls), 3),
        "wall_ms_p50": round(p50(wall), 3),
        "wall_ms_p95": round(p95(wall), 3),
    }
    rec = recovery_rate(opportunities, recoveries)
    if rec is not None:
        out["recovery_rate"] = round(rec, 4)
    return out
