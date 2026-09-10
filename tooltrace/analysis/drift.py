"""Drift, silent decay, and error budgets for agent reliability.

Half of enterprises have shipped an agent that passed internal evaluation and
still caused a customer-facing failure. The gap between those two facts is
usually not a sudden break — it is drift: a model updated behind an API, a prompt
edited, a tool's output format changed, and a success rate that slides two points
a week until somebody notices.

Two measurements, and one budget:

- **Drift** compares two windows of runs and reports whether behaviour moved, on
  more than accuracy. An agent whose success rate is unchanged while its step
  count doubled has changed, and a rate-only monitor is blind to it. That is the
  "silent decay" case: passes evals, costs three times as much, and nothing
  fires.
- **An error budget** turns an SLO into something with a number attached. "99%
  reliability" is unactionable; "you have 4 failures of budget left this window"
  is a decision.

The discipline throughout is the one `pr_report` established: a change has to be
**real** before it is reported. A monitor that fires on noise gets muted, and a
muted monitor is worse than none because it is believed to be watching.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean
from typing import Any

from tooltrace.analysis.stats import bootstrap_interval, wilson_interval

#: Windows smaller than this cannot support a drift claim. Same threshold and
#: same reason as `analysis/power.py`.
MIN_WINDOW = 10

#: Metrics watched for drift, with the direction that counts as worse and the
#: smallest relative move worth reporting. Relative rather than absolute because
#: these are on wildly different scales.
WATCHED: dict[str, dict[str, Any]] = {
    "success_rate": {"kind": "proportion", "direction": "higher_is_better", "min_move": 0.10},
    "steps": {"kind": "mean", "direction": "lower_is_better", "min_move_pct": 0.25},
    "wall_ms": {"kind": "mean", "direction": "lower_is_better", "min_move_pct": 0.50},
    "failed_tool_calls": {"kind": "mean", "direction": "lower_is_better", "min_move": 0.5},
    "tool_calls": {"kind": "mean", "direction": "lower_is_better", "min_move_pct": 0.25},
}

DRIFTED = "drifted"
STABLE = "stable"
INCONCLUSIVE = "inconclusive"


def _values(runs: Sequence[dict[str, Any]], metric: str) -> list[float]:
    if metric == "success_rate":
        return [1.0 if r.get("success") else 0.0 for r in runs]
    return [float(r[metric]) for r in runs if isinstance(r.get(metric), int | float)]


def _interval(values: list[float], kind: str) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    if kind == "proportion":
        # Wilson, not bootstrap: a window of all-successes bootstraps to a
        # zero-width interval, and "the rate is exactly 1.0 with no uncertainty"
        # would make every subsequent window look like drift.
        return wilson_interval(int(sum(values)), len(values))
    return bootstrap_interval(values)


def compare_windows(
    baseline: Sequence[dict[str, Any]],
    current: Sequence[dict[str, Any]],
    *,
    metrics: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Has behaviour moved between two windows of runs?

    Reports every watched metric, not just accuracy. An agent whose success rate
    held while its step count doubled has changed, and that is the case a
    rate-only monitor is structurally unable to see.
    """
    watched = list(metrics or WATCHED)
    findings: list[dict[str, Any]] = []

    if len(baseline) < MIN_WINDOW or len(current) < MIN_WINDOW:
        return {
            "measurable": False,
            "reason": (
                f"windows of {len(baseline)} and {len(current)} runs; at least {MIN_WINDOW} "
                "each are needed before a move can be told from noise"
            ),
            "baseline_runs": len(baseline),
            "current_runs": len(current),
            "findings": [],
        }

    for metric in watched:
        spec = WATCHED.get(metric)
        if spec is None:
            continue
        before, after = _values(baseline, metric), _values(current, metric)
        if not before or not after:
            continue

        mean_before, mean_after = fmean(before), fmean(after)
        delta = mean_after - mean_before
        low_b = _interval(before, str(spec["kind"]))
        low_c = _interval(after, str(spec["kind"]))

        if low_b is None or low_c is None:
            verdict, note = INCONCLUSIVE, "not enough runs to form an interval"
        else:
            # Overlapping intervals mean the move is not established. This is
            # the conservative reading and it is the right one for a monitor:
            # firing on noise is how a monitor gets muted.
            overlap = not (low_c[0] > low_b[1] or low_b[0] > low_c[1])
            threshold = (
                abs(mean_before) * float(spec["min_move_pct"])
                if "min_move_pct" in spec
                else float(spec["min_move"])
            )
            matters = abs(delta) >= threshold
            if overlap:
                verdict, note = STABLE, "intervals overlap; no move the windows can establish"
            elif not matters:
                verdict, note = (
                    STABLE,
                    f"moved {delta:+.4f}, below the {threshold:.4f} that would matter",
                )
            else:
                worse = delta > 0 if spec["direction"] == "lower_is_better" else delta < 0
                verdict = DRIFTED
                note = (
                    f"moved {delta:+.4f}, {'worse' if worse else 'better'} and beyond the "
                    f"{threshold:.4f} that matters"
                )

        findings.append(
            {
                "metric": metric,
                "baseline": round(mean_before, 6),
                "current": round(mean_after, 6),
                "delta": round(delta, 6),
                "verdict": verdict,
                "note": note,
            }
        )

    drifted = [f for f in findings if f["verdict"] == DRIFTED]
    accuracy = next((f for f in findings if f["metric"] == "success_rate"), None)
    silent = bool(drifted and accuracy is not None and accuracy["verdict"] != DRIFTED)

    return {
        "measurable": True,
        "baseline_runs": len(baseline),
        "current_runs": len(current),
        "findings": findings,
        "drifted": [f["metric"] for f in drifted],
        # The finding a success-rate monitor cannot produce: behaviour changed
        # and accuracy did not. "Passes evals, fails in production" starts here.
        "silent_decay": silent,
        "statement": (
            "Behaviour moved on "
            + ", ".join(f["metric"] for f in drifted)
            + " while the success rate held. An accuracy-only monitor would report nothing."
            if silent
            else "No metric moved beyond what these windows can establish."
            if not drifted
            else "Accuracy moved, along with " + ", ".join(f["metric"] for f in drifted) + "."
        ),
    }


# --- error budgets ----------------------------------------------------------


def error_budget(
    runs: Sequence[dict[str, Any]], *, objective: float, window: str = "this window"
) -> dict[str, Any]:
    """How much failure an SLO still allows.

    "99% reliability" is unactionable. "Four failures of budget left" is a
    decision, and it is the same number expressed usefully.

    Deliberately reports a **negative** remaining budget rather than clamping to
    zero: "you are eleven failures over" and "you are exactly at your limit" call
    for different responses, and clamping erases the difference.
    """
    total = len(runs)
    if total == 0:
        return {
            "measurable": False,
            "reason": "no runs in this window",
            "objective": objective,
        }
    if not 0.0 < objective <= 1.0:
        return {
            "measurable": False,
            "reason": f"objective {objective} is not a rate between 0 and 1",
        }

    failures = sum(1 for r in runs if not r.get("success"))
    allowed = (1.0 - objective) * total
    remaining = allowed - failures
    rate = 1.0 - failures / total
    low, high = wilson_interval(total - failures, total)

    return {
        "measurable": True,
        "window": window,
        "runs": total,
        "objective": objective,
        "measured_rate": round(rate, 6),
        "ci95": [round(low, 6), round(high, 6)],
        "failures": failures,
        "budget": round(allowed, 3),
        # Negative when over. Clamping would erase the difference between "at
        # the limit" and "far past it".
        "remaining": round(remaining, 3),
        "exhausted": remaining < 0,
        # The caveat that stops an SLO being read as established fact on a small
        # window: the interval may straddle the objective entirely.
        "objective_is_within_interval": low <= objective <= high,
        "statement": (
            f"{failures} failure(s) against a budget of {allowed:.1f} over {total} run(s). "
            + (
                "The measured rate's confidence interval contains the objective, so this "
                "window cannot establish whether the objective is met."
                if low <= objective <= high
                else "The interval excludes the objective."
            )
        ),
    }
