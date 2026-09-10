"""Sample-size planning, and separating the agent's noise from the harness's.

Every number this project produces already carries a confidence interval, and
every one of them is computed *after* the runs. That leaves the most consequential
decision unsupported: how many runs to do. People pick 3, or 10, because they are
round numbers, and then read a difference the sample cannot support — the exact
failure `showdown` and `pr-report` exist to prevent, addressed one step too late.

Two numbers here are worth stating outright because they are surprising, and
because a planner nobody believes is a planner nobody uses: detecting a
**10-point** difference in success rate at a 50% baseline takes about **393 runs
per arm**, and a 5-point difference takes about **1570**. A 3-run sweep does not
compare agents. It demonstrates that something runs.

The tests below pin those figures, pin the refusals (a normal approximation on
four runs produces a number, and the number is not information), and check the
variance split — which exists because "this agent is flaky" and "this benchmark
covers diverse tasks" produce the same standard deviation and have opposite
meanings.
"""

from __future__ import annotations

import json

import pytest
from tooltrace.analysis.power import (
    MIN_TRUSTWORTHY_N,
    bayesian_comparison,
    minimum_detectable_effect,
    power_report,
    runs_for_effect,
    variance_decomposition,
)
from tooltrace.cli.main import main

# --- minimum detectable effect ----------------------------------------------


def test_more_runs_detect_smaller_differences() -> None:
    assert minimum_detectable_effect(1000) < minimum_detectable_effect(100)
    assert minimum_detectable_effect(100) < minimum_detectable_effect(10)


def test_the_standard_figures_are_what_they_should_be() -> None:
    """A planner whose numbers disagree with the textbook is not usable."""
    assert runs_for_effect(0.10) == pytest.approx(393, abs=2)
    assert runs_for_effect(0.05) == pytest.approx(1570, abs=5)
    assert runs_for_effect(0.20) == pytest.approx(99, abs=2)


def test_a_tiny_sample_gets_no_number_at_all() -> None:
    """A normal approximation on four runs produces a number, not information."""
    assert minimum_detectable_effect(4) is None
    assert minimum_detectable_effect(MIN_TRUSTWORTHY_N - 1) is None
    assert minimum_detectable_effect(MIN_TRUSTWORTHY_N) is not None


def test_the_default_baseline_is_the_conservative_one() -> None:
    """Variance in a proportion peaks at 0.5, so 0.5 is the worst case.

    Assuming a 0.95 baseline would promise more sensitivity than a sweep
    delivers, which is the direction a planner must never err in.
    """
    worst = minimum_detectable_effect(100, baseline_rate=0.5)
    optimistic = minimum_detectable_effect(100, baseline_rate=0.95)
    assert worst > optimistic
    assert minimum_detectable_effect(100) == worst


def test_a_boundary_baseline_is_refused_rather_than_promising_certainty() -> None:
    # p=1.0 has zero variance under this approximation, which would imply
    # infinite sensitivity. It does not; the approximation does not apply.
    assert minimum_detectable_effect(100, baseline_rate=1.0) is None
    assert runs_for_effect(0.1, baseline_rate=0.0) is None


def test_asking_how_many_runs_detect_nothing_has_no_answer() -> None:
    assert runs_for_effect(0.0) is None
    assert runs_for_effect(-0.1) is None


def test_the_answer_is_never_below_the_trustworthy_floor() -> None:
    # A huge effect mathematically needs 2 runs; 2 runs still cannot support it.
    assert runs_for_effect(0.99) >= MIN_TRUSTWORTHY_N


def test_planning_is_deterministic() -> None:
    """A planner returning a different number each call is worse than none."""
    assert power_report(50) == power_report(50)


# --- the report says what a sweep cannot do ---------------------------------


def test_a_small_sweep_is_told_it_cannot_compare_agents() -> None:
    report = power_report(3)
    assert report["minimum_detectable_effect"] is None
    assert "cannot compare two agents" in report["statement"]


def test_a_large_sweep_states_its_sensitivity() -> None:
    report = power_report(400)
    assert "will not be distinguishable from noise" in report["statement"]


def test_the_report_warns_against_the_inverse_reading() -> None:
    """ "We saw no difference" is not "there is no difference"."""
    assert "not evidence of no difference" in power_report(400)["statement"]


def test_the_independence_assumption_is_stated() -> None:
    """Shared caches and seeds are the usual reason this understates the need."""
    assert "not independent" in power_report(100)["assumption"]


# --- variance decomposition -------------------------------------------------


def rows(*specs: tuple[str, str, bool]) -> list[dict]:
    return [{"agent": a, "task_id": t, "success": s} for a, t, s in specs]


def test_a_stable_agent_on_diverse_tasks_is_not_flaky() -> None:
    """The conflation this exists to undo.

    Perfect on one task, hopeless on another, entirely repeatable on both. A
    single standard deviation calls that instability; it is the benchmark
    covering a range.
    """
    got = variance_decomposition(
        rows(
            ("a", "easy", True),
            ("a", "easy", True),
            ("a", "hard", False),
            ("a", "hard", False),
        )
    )
    assert got["within_configuration_variance"] == 0.0
    assert got["between_task_variance"] > 0
    assert got["nondeterminism_share"] == 0.0


def test_a_coin_flipping_agent_is_flaky() -> None:
    got = variance_decomposition(
        rows(
            ("a", "t", True),
            ("a", "t", False),
            ("a", "t", True),
            ("a", "t", False),
        )
    )
    assert got["within_configuration_variance"] > 0
    assert got["nondeterminism_share"] == 1.0


def test_no_repeat_means_nondeterminism_cannot_be_observed() -> None:
    """One run per configuration cannot show run-to-run variation at all."""
    got = variance_decomposition(rows(("a", "t1", True), ("a", "t2", False)))
    assert got["measurable"] is False
    assert "more than once" in got["reason"]


def test_zero_variance_reports_no_share_rather_than_zero() -> None:
    """ "0% of the variance is noise" and "there was no variance" differ."""
    got = variance_decomposition(rows(("a", "t", True), ("a", "t", True)))
    assert got["nondeterminism_share"] is None


def test_it_states_that_it_cannot_separate_model_from_harness() -> None:
    got = variance_decomposition(rows(("a", "t", True), ("a", "t", False)))
    assert "cannot separate them" in got["note"]


def test_two_agents_are_separate_configurations() -> None:
    got = variance_decomposition(
        rows(("a", "t", True), ("a", "t", True), ("b", "t", False), ("b", "t", False))
    )
    assert got["configurations"] == 2
    assert got["between_task_variance"] > 0


# --- Bayesian comparison ----------------------------------------------------


def test_a_clear_winner_reads_as_one() -> None:
    got = bayesian_comparison(190, 200, 100, 200, label_a="fast", label_b="slow")
    assert got["probability_a_better"] > 0.99
    assert "fast is better" in got["reading"]


def test_a_tie_is_an_absence_of_evidence_not_evidence_of_equality() -> None:
    """The misreading this phrasing exists to block."""
    got = bayesian_comparison(100, 200, 100, 200)
    assert 0.4 < got["probability_a_better"] < 0.6
    assert "absence of evidence" in got["reading"]
    assert "evidence the two are equal" in got["reading"]


def test_a_tiny_sample_says_the_prior_is_doing_the_work() -> None:
    got = bayesian_comparison(3, 3, 0, 3)
    assert "dominated by the prior" in got["reading"]


def test_the_prior_is_stated_and_never_inferred() -> None:
    """A prior chosen after seeing the data is how this becomes rhetoric."""
    assert bayesian_comparison(5, 10, 5, 10)["prior"] == "Beta(1.0, 1.0)"
    assert bayesian_comparison(5, 10, 5, 10, prior_alpha=2, prior_beta=8)["prior"] == "Beta(2, 8)"


def test_the_two_probabilities_are_complementary() -> None:
    got = bayesian_comparison(30, 50, 20, 50)
    assert got["probability_a_better"] + got["probability_b_better"] == pytest.approx(1.0, abs=1e-6)


def test_comparing_an_agent_with_itself_keeps_both_arms() -> None:
    """`showdown` compares an agent with itself as a sanity check.

    A posterior keyed by label collapses the two arms into one -- losing exactly
    the arm the check exists to compare.
    """
    got = bayesian_comparison(9, 10, 9, 10, label_a="same", label_b="same")
    assert len(got["posterior_mean"]) == 2
    assert got["probability_a_better"] == pytest.approx(0.5, abs=0.01)


def test_an_empty_arm_is_not_measurable() -> None:
    assert bayesian_comparison(0, 0, 5, 10)["measurable"] is False


# --- the CLI ----------------------------------------------------------------


def test_the_cli_answers_what_a_sweep_can_detect(capsys) -> None:
    assert main(["power", "--runs", "30", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs_per_arm"] == 30
    assert payload["runs_needed_for"]["0.10"] == pytest.approx(393, abs=2)


def test_the_cli_answers_how_many_runs_an_effect_needs(capsys) -> None:
    assert main(["power", "--detect", "0.10", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs_per_arm"] == pytest.approx(393, abs=2)


def test_the_cli_refuses_a_non_positive_effect(capsys) -> None:
    assert main(["power", "--detect", "0"]) != 0
    assert "positive difference" in capsys.readouterr().err


def test_the_human_output_leads_with_the_limitation(capsys) -> None:
    main(["power", "--runs", "5"])
    assert "cannot compare two agents" in capsys.readouterr().out


# --- showdown carries all three ---------------------------------------------


def test_showdown_reports_what_its_sample_could_have_detected(capsys) -> None:
    """Without this, "not distinguishable" reads as "these are the same"."""
    assert main(["showdown", "--agents", "scripted", "--runs", "2", "--limit", "1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "power" in payload
    assert payload["power"]["runs_per_arm"] == 2
    assert "variance" in payload


def test_showdown_reports_a_posterior_when_there_are_two_arms(capsys) -> None:
    code = main(
        ["showdown", "--agents", "scripted,scripted", "--runs", "2", "--limit", "1", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bayesian"]["measurable"] is True
    assert len(payload["bayesian"]["posterior_mean"]) == 2
