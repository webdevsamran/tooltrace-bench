"""Know what a sweep will cost before it runs, and stop it when it shouldn't.

`cost_summary` reports what a sweep *did* cost. That is the wrong end of the
problem for the decision people actually face, which is whether to start one. A
sweep across nine models and nine benchmarks cost the Holistic Agent Leaderboard
authors around $40,000; nobody should discover a number like that afterwards.

Four things, and the discipline in each is about refusing to invent:

- `forecast_spend` — an estimate, from **observed** token usage. With no
  observations it returns `measurable: false` rather than a plausible number. A
  forecast built on a guessed token count is a guess with a decimal point on it,
  and it would be believed.
- `BudgetGuard` — a hard ceiling. It stops, and it reports **what did not run**,
  because a truncated sweep silently reported as a complete one is the same
  defect class the `--limit` subset note exists to prevent.
- `cost_attribution` — where the money went, by task and by failure class.
  Spending 60% of a budget on runs that failed is the finding; a total cannot
  show it.
- `viability_verdict` — cost per resolved task against a stated human baseline.
  The baseline is an argument, never a default, because a viability verdict
  computed against a number this module chose would be this module's opinion
  wearing a measurement's clothes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

#: A forecast from fewer than this many observed runs is noise with a decimal
#: point. Stated as a constant so the threshold is arguable rather than buried.
MIN_OBSERVATIONS = 3


def _cost_of(result: dict[str, Any]) -> float | None:
    usage = result.get("usage") or {}
    cost = usage.get("provider_cost_reported")
    return float(cost) if isinstance(cost, int | float) else None


def _tokens_of(result: dict[str, Any]) -> int | None:
    tokens = (result.get("usage") or {}).get("tokens") or {}
    total = tokens.get("total_tokens")
    if isinstance(total, int):
        return total
    parts = [tokens.get("prompt_tokens"), tokens.get("completion_tokens")]
    measured = [p for p in parts if isinstance(p, int)]
    # A partial sum would understate. Either both halves are known or neither is.
    return sum(measured) if len(measured) == len(parts) else None


def observed_cost_per_run(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean cost and tokens per run, from runs that actually reported them."""
    costs = [c for c in (_cost_of(r) for r in results) if c is not None]
    tokens = [t for t in (_tokens_of(r) for r in results) if t is not None]
    currencies = sorted({str((r.get("usage") or {}).get("currency")) for r in results} - {"None"})
    return {
        "runs": len(results),
        "priced_runs": len(costs),
        "cost_per_run": round(sum(costs) / len(costs), 6) if costs else None,
        "tokens_per_run": round(sum(tokens) / len(tokens), 2) if tokens else None,
        "currency": currencies[0] if len(currencies) == 1 else None,
        # Mixed currencies cannot be summed, and summing them anyway is how a
        # cost report becomes fiction.
        "mixed_currencies": len(currencies) > 1,
    }


def forecast_spend(
    *, tasks: int, runs_per_task: int, observed: list[dict[str, Any]]
) -> dict[str, Any]:
    """Estimated spend for a planned sweep, from observed per-run cost.

    Returns `measurable: false` when there is nothing to extrapolate from. The
    alternative — assuming a token count and multiplying — produces a confident
    figure with no basis, and a confident figure is exactly what gets believed
    and budgeted against.
    """
    planned_runs = max(0, tasks) * max(0, runs_per_task)
    basis = observed_cost_per_run(observed)

    if basis["mixed_currencies"]:
        return {
            "measurable": False,
            "reason": "observed runs mix currencies; a single total would be meaningless",
            "planned_runs": planned_runs,
        }
    if basis["priced_runs"] < MIN_OBSERVATIONS or basis["cost_per_run"] is None:
        return {
            "measurable": False,
            "reason": (
                f"only {basis['priced_runs']} observed run(s) reported a cost; at least "
                f"{MIN_OBSERVATIONS} are needed before extrapolating"
            ),
            "planned_runs": planned_runs,
            "tokens_per_run": basis["tokens_per_run"],
        }

    per_run = float(basis["cost_per_run"])
    estimate = per_run * planned_runs
    return {
        "measurable": True,
        "planned_runs": planned_runs,
        "cost_per_run_observed": per_run,
        "estimate": round(estimate, 4),
        "currency": basis["currency"],
        "observations": basis["priced_runs"],
        # An interval, not a point. Cost per run varies with prompt length and
        # with how many steps a task takes, and a single figure invites a budget
        # set to exactly that number.
        "range": [round(estimate * 0.5, 4), round(estimate * 2.0, 4)],
        "assumption": (
            "Extrapolated from the mean cost of runs already observed. Longer tasks, "
            "more steps, a different model or a cold prompt cache all change it. The "
            "range is a rule of thumb, not a confidence interval."
        ),
    }


@dataclass
class BudgetGuard:
    """A hard spending ceiling for a sweep, with an alert before the stop.

    The stop is hard by design. A soft budget that logs and continues is a budget
    that does not exist, and the failure mode it guards against — a sweep left
    running overnight against a metered API — is precisely the one where nobody
    is watching the log.

    What did not run is recorded, because a sweep cut short and reported as
    complete is the same defect the `--limit` subset note exists to prevent: a
    partial measurement read as a full one.
    """

    ceiling: float
    currency: str = "USD"
    #: Fraction of the ceiling at which to warn. A stop with no warning gives a
    #: caller no chance to raise the limit deliberately.
    alert_at: float = 0.8
    spent: float = 0.0
    runs_completed: int = 0
    runs_skipped: int = 0
    alerts: list[str] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str = ""

    def would_exceed(self, next_cost: float) -> bool:
        return self.spent + next_cost > self.ceiling

    def record(self, cost: float | None) -> None:
        """Record one completed run. `None` is an unpriced run, not a free one."""
        self.runs_completed += 1
        if cost is None:
            # Counting an unpriced run as 0.0 would let an unpriced sweep run
            # forever under any ceiling.
            if "unpriced" not in " ".join(self.alerts):
                self.alerts.append(
                    "a run reported no cost; unpriced runs are not counted against the "
                    "ceiling and this budget therefore does not bound them"
                )
            return
        self.spent += cost
        ratio = self.spent / self.ceiling if self.ceiling > 0 else float("inf")
        if ratio >= self.alert_at and not self.stopped:
            message = f"spent {self.spent:.4f} of {self.ceiling:.4f} {self.currency}"
            if message not in self.alerts:
                self.alerts.append(message)

    def stop(self, reason: str, *, remaining: int = 0) -> None:
        self.stopped = True
        self.stop_reason = reason
        self.runs_skipped = remaining

    def to_dict(self) -> dict[str, Any]:
        return {
            "ceiling": self.ceiling,
            "currency": self.currency,
            "spent": round(self.spent, 6),
            "remaining": round(max(0.0, self.ceiling - self.spent), 6),
            "runs_completed": self.runs_completed,
            "runs_skipped": self.runs_skipped,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "alerts": self.alerts,
            # The field that stops a truncated sweep reading as a whole one.
            "is_partial": self.stopped or self.runs_skipped > 0,
        }


def cost_attribution(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Where the money went: by task, and by how the run ended.

    The second breakdown is the one a total hides. Spending most of a budget on
    runs that failed is a finding about the task set or the agent, and it is
    invisible in a single number.
    """
    by_task: dict[str, list[float]] = defaultdict(list)
    by_outcome: dict[str, list[float]] = defaultdict(list)
    unpriced = 0

    for result in results:
        cost = _cost_of(result)
        if cost is None:
            unpriced += 1
            continue
        by_task[str(result.get("task_id", ""))].append(cost)
        outcome = (
            "success" if result.get("success") else str(result.get("failure_reason") or "fail")
        )
        by_outcome[outcome].append(cost)

    total = sum(sum(v) for v in by_task.values())
    if total <= 0:
        return {
            "measurable": False,
            "reason": "no run reported a cost, so there is nothing to attribute",
            "unpriced_runs": unpriced,
        }

    def block(groups: dict[str, list[float]]) -> list[dict[str, Any]]:
        return sorted(
            (
                {
                    "key": key,
                    "runs": len(values),
                    "cost": round(sum(values), 6),
                    "share": round(sum(values) / total, 6),
                }
                for key, values in groups.items()
            ),
            key=lambda row: -float(row["cost"]),
        )

    wasted = sum(sum(v) for k, v in by_outcome.items() if k != "success")
    return {
        "measurable": True,
        "total": round(total, 6),
        "by_task": block(by_task),
        "by_outcome": block(by_outcome),
        "spent_on_failures": round(wasted, 6),
        "failure_share": round(wasted / total, 6),
        # Runs with no price are excluded from every share above, so a report
        # over a partly-priced sweep describes only the priced part.
        "unpriced_runs": unpriced,
        "covers_all_runs": unpriced == 0,
    }


def viability_verdict(
    *,
    cost_per_resolved_task: float | None,
    human_baseline_cost: float | None,
    success_rate: float | None,
    currency: str = "USD",
) -> dict[str, Any]:
    """Is this agent cheaper than the alternative, under stated assumptions?

    `human_baseline_cost` has no default and never will. A verdict computed
    against a number this module picked would be this module's opinion wearing a
    measurement's clothes, and "economically viable" is exactly the phrase that
    gets quoted without its assumptions.

    The success rate is part of the verdict rather than a footnote: an agent that
    resolves 40% of tasks needs someone to handle the other 60%, and a cost per
    *resolved* task that ignores that is comparing an agent's best case against a
    human's average one.
    """
    if cost_per_resolved_task is None:
        return {
            "measurable": False,
            "reason": "no run reported a cost, so cost per resolved task is unknown",
        }
    if human_baseline_cost is None:
        return {
            "measurable": False,
            "reason": (
                "no human baseline cost was supplied. This has no default: a viability "
                "verdict against an invented baseline is an opinion, not a measurement"
            ),
            "cost_per_resolved_task": cost_per_resolved_task,
        }

    ratio = cost_per_resolved_task / human_baseline_cost if human_baseline_cost > 0 else None
    unresolved = 1.0 - success_rate if isinstance(success_rate, int | float) else None

    if ratio is None:
        verdict = "undetermined"
    elif ratio < 0.5:
        verdict = "cheaper_per_resolved_task"
    elif ratio > 2.0:
        verdict = "more_expensive_per_resolved_task"
    else:
        verdict = "comparable"

    assumptions = [
        f"Human baseline of {human_baseline_cost:.4f} {currency} per task was supplied, "
        "not measured here.",
        "Cost per *resolved* task counts only successes; the agent's failed runs are "
        "already amortised into it.",
    ]
    if unresolved is not None and unresolved > 0:
        assumptions.append(
            f"{unresolved * 100:.0f}% of tasks were not resolved at all. Someone still has "
            "to do those, and that cost is not in this comparison."
        )
    else:
        assumptions.append(
            "No success rate was supplied, so the cost of unresolved work is not accounted for."
        )
    assumptions.append(
        "Nothing here prices review, rework, or the consequences of a wrong answer that passed."
    )

    return {
        "measurable": True,
        "verdict": verdict,
        "cost_per_resolved_task": cost_per_resolved_task,
        "human_baseline_cost": human_baseline_cost,
        "ratio": round(ratio, 4) if ratio is not None else None,
        "currency": currency,
        "assumptions": assumptions,
    }
