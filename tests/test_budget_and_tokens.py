"""What a sweep costs, before and after — and every place it must refuse to guess.

`cost_summary` reported what a sweep *did* cost. That is the wrong end of the
decision people face, which is whether to start one: the Holistic Agent
Leaderboard sweep ran to roughly $40,000, and nobody should learn a number like
that afterwards.

Most of what follows tests refusals, because every function here has an obvious
wrong answer that looks like an answer:

- A forecast with no observations could multiply an assumed token count and
  return a confident figure. It would be believed and budgeted against.
- A budget could count an unpriced run as free, and then bound nothing while
  appearing to bound everything.
- A viability verdict could default the human baseline, and become this module's
  opinion wearing a measurement's clothes.
- A cost report could bill cached prompt tokens at the full input rate, which is
  wrong by an order of magnitude on a cache-heavy run — or bill them *twice* by
  adding them to the prompt count they are already part of.
"""

from __future__ import annotations

import json

import pytest
from tooltrace.agents.interop import PriceTable
from tooltrace.cli.main import main
from tooltrace.core.models import TokenUsage
from tooltrace.metrics.budget import (
    MIN_OBSERVATIONS,
    BudgetGuard,
    cost_attribution,
    forecast_spend,
    observed_cost_per_run,
    viability_verdict,
)

TABLE = PriceTable.model_validate(
    {
        "prices": {
            "cheap": [
                {
                    "input_per_1k": 1.0,
                    "output_per_1k": 3.0,
                    "cached_input_per_1k": 0.1,
                    "cache_write_per_1k": 1.25,
                    "effective_from": "2026-01-01",
                }
            ],
            "no-cache-rate": [
                {"input_per_1k": 1.0, "output_per_1k": 3.0, "effective_from": "2026-01-01"}
            ],
        }
    }
)


def run(cost: float | None, *, success: bool = True, task: str = "a", reason: str = "none") -> dict:
    return {
        "task_id": task,
        "success": success,
        "failure_reason": reason,
        "usage": {
            "provider_cost_reported": cost,
            "currency": "USD" if cost is not None else None,
            "tokens": {"total_tokens": 1500},
        },
    }


# --- token dimensions -------------------------------------------------------


def test_the_new_dimensions_are_optional_so_old_bundles_still_parse() -> None:
    """`EvalResult` is do-not-touch; every addition here defaults to None.

    Bumping the schema version for an optional field would make every committed
    bundle incomparable with every new one -- a far larger cost than it avoids.
    """
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert usage.cached_prompt_tokens is None
    assert usage.cache_write_tokens is None
    assert usage.reasoning_tokens is None


def test_cached_tokens_are_a_subset_not_an_addition() -> None:
    """A provider reports 10,000 prompt tokens of which 9,000 were cached.

    Charging for 19,000 is plainly wrong, and it is what adding them does.
    """
    full = TABLE.compute_cost("cheap", 10_000, 0, "2026-09-09")["cost"]
    cached = TABLE.compute_cost("cheap", 10_000, 0, "2026-09-09", cached_input_tokens=10_000)[
        "cost"
    ]
    assert full == pytest.approx(10.0)
    assert cached == pytest.approx(1.0), "10,000 tokens at the cached rate, not 20,000 at any rate"


def test_a_cache_heavy_run_costs_far_less() -> None:
    plain = TABLE.compute_cost("cheap", 10_000, 1_000, "2026-09-09")["cost"]
    cached = TABLE.compute_cost("cheap", 10_000, 1_000, "2026-09-09", cached_input_tokens=9_000)[
        "cost"
    ]
    assert cached < plain / 2


def test_an_unstated_cached_rate_bills_at_the_full_rate_and_says_so() -> None:
    """Over-estimating is the only direction a cost figure may err in."""
    got = TABLE.compute_cost("no-cache-rate", 10_000, 0, "2026-09-09", cached_input_tokens=9_000)
    assert got["cost"] == pytest.approx(10.0)
    assert got["cached_rate_stated"] is False


def test_a_stated_cached_rate_is_marked_as_stated() -> None:
    got = TABLE.compute_cost("cheap", 1_000, 0, "2026-09-09", cached_input_tokens=1_000)
    assert got["cached_rate_stated"] is True


def test_more_cached_tokens_than_prompt_tokens_is_clamped() -> None:
    """A provider that reports nonsense must not produce a negative cost."""
    got = TABLE.compute_cost("cheap", 100, 0, "2026-09-09", cached_input_tokens=10_000)
    assert got["cost"] >= 0
    assert got["cached_input_tokens"] == 100


def test_reasoning_tokens_bill_as_output() -> None:
    got = TABLE.compute_cost("cheap", 0, 0, "2026-09-09", reasoning_tokens=1_000)
    assert got["cost"] == pytest.approx(3.0)


def test_cache_writes_are_charged_only_when_a_rate_is_stated() -> None:
    charged = TABLE.compute_cost("cheap", 0, 0, "2026-09-09", cache_write_tokens=1_000)["cost"]
    uncharged = TABLE.compute_cost("no-cache-rate", 0, 0, "2026-09-09", cache_write_tokens=1_000)[
        "cost"
    ]
    assert charged == pytest.approx(1.25)
    assert uncharged == 0.0


def test_an_unpriced_model_still_refuses_to_guess() -> None:
    with pytest.raises(KeyError, match="instead of guessing"):
        TABLE.compute_cost("unknown", 1, 1, "2026-09-09")
    assert TABLE.compute_cost("unknown", 1, 1, "2026-09-09", allow_unpriced=True)["cost"] is None


# --- forecasting ------------------------------------------------------------


def test_a_forecast_needs_observations() -> None:
    """Multiplying an assumed token count returns a confident figure with no basis."""
    got = forecast_spend(tasks=20, runs_per_task=10, observed=[run(0.02)])
    assert got["measurable"] is False
    assert str(MIN_OBSERVATIONS) in got["reason"]


def test_a_forecast_extrapolates_from_what_was_seen() -> None:
    got = forecast_spend(tasks=20, runs_per_task=10, observed=[run(0.02) for _ in range(5)])
    assert got["measurable"] is True
    assert got["planned_runs"] == 200
    assert got["estimate"] == pytest.approx(4.0)


def test_a_forecast_is_a_range_not_a_point() -> None:
    """A single figure invites a budget set to exactly that number."""
    got = forecast_spend(tasks=10, runs_per_task=10, observed=[run(0.02) for _ in range(5)])
    low, high = got["range"]
    assert low < got["estimate"] < high
    assert "not a confidence interval" in got["assumption"]


def test_mixed_currencies_cannot_be_forecast() -> None:
    mixed = [run(0.02), run(0.02), run(0.02)]
    mixed[0]["usage"]["currency"] = "EUR"
    got = forecast_spend(tasks=10, runs_per_task=1, observed=mixed)
    assert got["measurable"] is False
    assert "currencies" in got["reason"]


def test_unpriced_runs_do_not_count_as_observations() -> None:
    got = forecast_spend(tasks=10, runs_per_task=1, observed=[run(None) for _ in range(20)])
    assert got["measurable"] is False


def test_a_partial_token_count_is_not_summed() -> None:
    """Half of a sum understates, and understating a cost is the bad direction."""
    partial = run(0.01)
    partial["usage"]["tokens"] = {"prompt_tokens": 100, "completion_tokens": None}
    assert observed_cost_per_run([partial])["tokens_per_run"] is None


# --- the budget guard -------------------------------------------------------


def test_it_stops_rather_than_logging_and_continuing() -> None:
    """A soft budget is a budget that does not exist."""
    guard = BudgetGuard(ceiling=0.10)
    for _ in range(5):
        guard.record(0.02)
    assert guard.would_exceed(0.02) is True
    guard.stop("ceiling reached", remaining=3)
    assert guard.stopped is True


def test_a_stopped_sweep_records_what_did_not_run() -> None:
    """A truncated measurement read as a complete one is the defect to avoid."""
    guard = BudgetGuard(ceiling=0.10)
    guard.record(0.10)
    guard.stop("ceiling reached", remaining=7)
    got = guard.to_dict()
    assert got["runs_skipped"] == 7
    assert got["is_partial"] is True


def test_a_completed_sweep_is_not_marked_partial() -> None:
    guard = BudgetGuard(ceiling=10.0)
    guard.record(0.01)
    assert guard.to_dict()["is_partial"] is False


def test_it_warns_before_it_stops() -> None:
    """A stop with no warning gives a caller no chance to raise the limit."""
    guard = BudgetGuard(ceiling=1.0, alert_at=0.8)
    guard.record(0.5)
    assert guard.alerts == []
    guard.record(0.4)
    assert guard.alerts


def test_an_unpriced_run_is_not_free() -> None:
    """Counting it as 0.0 would let an unpriced sweep run forever under any ceiling.

    The guard cannot bound what nobody priced, and the honest response is to say
    so rather than to appear to bound it.
    """
    guard = BudgetGuard(ceiling=0.001)
    guard.record(None)
    guard.record(None)
    assert guard.spent == 0.0
    assert guard.stopped is False
    assert any("does not bound them" in a for a in guard.alerts)


def test_the_unpriced_warning_is_not_repeated_per_run() -> None:
    guard = BudgetGuard(ceiling=1.0)
    for _ in range(10):
        guard.record(None)
    assert len(guard.alerts) == 1


# --- attribution ------------------------------------------------------------


def test_it_shows_what_was_spent_on_failures() -> None:
    """The finding a total hides."""
    got = cost_attribution(
        [run(0.05, success=False, reason="timeout"), run(0.01, success=True, task="b")]
    )
    assert got["failure_share"] == pytest.approx(0.8333, abs=1e-3)
    assert got["by_outcome"][0]["key"] == "timeout"


def test_it_breaks_down_by_task() -> None:
    got = cost_attribution([run(0.05, task="expensive"), run(0.01, task="cheap")])
    assert [row["key"] for row in got["by_task"]] == ["expensive", "cheap"]


def test_it_says_when_it_does_not_cover_every_run() -> None:
    """Shares over a partly-priced sweep describe only the priced part."""
    got = cost_attribution([run(0.05), run(None)])
    assert got["unpriced_runs"] == 1
    assert got["covers_all_runs"] is False


def test_nothing_priced_is_not_measurable_rather_than_zero() -> None:
    got = cost_attribution([run(None), run(None)])
    assert got["measurable"] is False
    assert "nothing to attribute" in got["reason"]


# --- viability --------------------------------------------------------------


def test_the_human_baseline_has_no_default() -> None:
    """A verdict against an invented baseline is an opinion in a measurement's clothes."""
    got = viability_verdict(cost_per_resolved_task=0.1, human_baseline_cost=None, success_rate=0.9)
    assert got["measurable"] is False
    assert "no default" in got["reason"]


def test_a_much_cheaper_agent_reads_as_cheaper() -> None:
    got = viability_verdict(cost_per_resolved_task=0.10, human_baseline_cost=5.0, success_rate=0.9)
    assert got["verdict"] == "cheaper_per_resolved_task"


def test_a_much_dearer_agent_reads_as_dearer() -> None:
    got = viability_verdict(cost_per_resolved_task=50.0, human_baseline_cost=5.0, success_rate=0.9)
    assert got["verdict"] == "more_expensive_per_resolved_task"


def test_unresolved_work_is_named_in_the_assumptions() -> None:
    """An agent resolving 40% needs someone for the other 60%, and that is not priced."""
    got = viability_verdict(cost_per_resolved_task=0.10, human_baseline_cost=5.0, success_rate=0.4)
    assert any("60% of tasks were not resolved" in a for a in got["assumptions"])


def test_a_missing_success_rate_is_called_out_not_ignored() -> None:
    got = viability_verdict(cost_per_resolved_task=0.10, human_baseline_cost=5.0, success_rate=None)
    assert any("not accounted for" in a for a in got["assumptions"])


def test_the_unpriceable_costs_are_always_stated() -> None:
    got = viability_verdict(cost_per_resolved_task=0.1, human_baseline_cost=5.0, success_rate=1.0)
    assert any("review, rework" in a for a in got["assumptions"])


# --- the CLI ----------------------------------------------------------------


def test_the_cost_command_is_honest_about_an_unpriced_dataset(capsys) -> None:
    """No adapter in this repository reports spend. It must say so, not show zeros."""
    assert main(["cost", "--bundles", "results", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["attribution"]["measurable"] is False
    assert payload["viability"]["measurable"] is False


def test_the_cost_command_needs_bundles(capsys, tmp_path) -> None:
    assert main(["cost", "--bundles", str(tmp_path)]) != 0
    assert "no bundles" in capsys.readouterr().err


def test_a_budgeted_sweep_reports_its_budget(capsys) -> None:
    code = main(
        [
            "benchmark",
            "--task",
            "file-editing/fix-config-typo",
            "--agent",
            "scripted",
            "--runs",
            "2",
            "--budget",
            "1.0",
            "--summary",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    budget = payload["summary"]["overall"]["budget"]
    assert budget["ceiling"] == 1.0
    # The scripted agent reports no cost, so the guard says plainly that it is
    # not bounding anything rather than appearing to.
    assert any("does not bound them" in a for a in budget["alerts"])


def test_a_sweep_records_planned_against_completed(capsys) -> None:
    main(
        [
            "benchmark",
            "--task",
            "file-editing/fix-config-typo",
            "--agent",
            "scripted",
            "--runs",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["config"]["runs_planned"] == 2
    assert payload["config"]["runs_completed"] == 2
    assert payload["config"]["budget_stopped"] is False
