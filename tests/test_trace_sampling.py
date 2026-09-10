"""Which traces to score, and undoing the bias you chose on purpose.

At production volume something has to choose, and the choice is where most of
the damage in an evaluation pipeline gets done.

Uniform sampling is the usual default and the wrong one. The thing worth finding
is failure, failure is rare, and 1% of traffic yields 1% of the failures -- a
class that happens twice a week becomes one you see about once a year. Every
review then looks at a sample in which everything worked.

So the default is stratified, which makes the sample **deliberately biased**,
and the tests below are mostly about that bias being recorded and reversible. A
pipeline that stratifies and then reports the raw sample rate is reporting a
number about its own sampling policy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tooltrace.ingest.sampling import (
    ALL,
    CLEAN,
    ERRORED,
    LONG,
    STRATIFIED,
    UNIFORM,
    classify,
    estimate_rate,
    sample,
)


def traces(count: int, *, failure_every: int = 50, long_every: int = 0) -> list[dict[str, Any]]:
    rows = []
    for i in range(count):
        failed = failure_every and i % failure_every == 0
        rows.append(
            {
                "trace_id": f"t{i}",
                "steps": 40 if long_every and i % long_every == 0 else 5,
                "failed": bool(failed),
                "success": not failed,
            }
        )
    return rows


# --- strata -----------------------------------------------------------------


def test_a_failed_trace_is_errored_whatever_else_is_true() -> None:
    """First match wins: an errored *and* long trace is kept as an error."""
    assert classify({"failed": True, "steps": 99}) == ERRORED
    assert classify({"status": "error"}) == ERRORED
    assert classify({"error": "boom"}) == ERRORED


def test_a_long_successful_trace_is_its_own_stratum() -> None:
    """An agent that took forty steps to succeed has a problem the success rate
    cannot see."""
    assert classify({"steps": 40}) == LONG


def test_a_short_successful_trace_is_clean() -> None:
    assert classify({"steps": 3}) == CLEAN


# --- the policies -----------------------------------------------------------


def test_stratified_keeps_every_error() -> None:
    chosen = sample(traces(500))
    assert chosen["kept_by_stratum"][ERRORED] == chosen["seen_by_stratum"][ERRORED]


def test_stratified_keeps_only_a_slice_of_the_clean_ones() -> None:
    chosen = sample(traces(1000))
    assert chosen["kept_by_stratum"].get(CLEAN, 0) < chosen["seen_by_stratum"][CLEAN] / 10


def test_uniform_finds_failures_at_the_rate_they_occur() -> None:
    """Which is the whole problem with it, and the statement says so."""
    chosen = sample(traces(1000), policy=UNIFORM, rate=0.05)
    assert "at the rate they occur" in chosen["statement"]
    assert chosen["is_biased"] is False


def test_all_keeps_everything_and_has_nothing_to_correct() -> None:
    chosen = sample(traces(100), policy=ALL)
    assert chosen["kept"] == 100
    assert "nothing to correct" in chosen["statement"]


def test_an_unknown_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown policy"):
        sample(traces(10), policy="reservoir")


# --- determinism ------------------------------------------------------------


def test_the_same_seed_keeps_the_same_traces() -> None:
    """A sampled evaluation that cannot be re-run is not reproducible."""
    first = sample(traces(500), seed=7)
    second = sample(traces(500), seed=7)
    assert [t["trace_id"] for t in first["traces"]] == [t["trace_id"] for t in second["traces"]]


def test_a_different_seed_keeps_a_different_set() -> None:
    first = {t["trace_id"] for t in sample(traces(500), seed=1)["traces"]}
    second = {t["trace_id"] for t in sample(traces(500), seed=2)["traces"]}
    assert first != second


def test_the_order_traces_arrive_in_does_not_change_the_sample() -> None:
    """A sequence-dependent draw would make a re-run that processed traces in a
    different order keep a different set."""
    rows = traces(300)
    forward = {t["trace_id"] for t in sample(rows, seed=3)["traces"]}
    backward = {t["trace_id"] for t in sample(list(reversed(rows)), seed=3)["traces"]}
    assert forward == backward


def test_a_trace_with_no_id_is_kept_rather_than_dropped() -> None:
    """Losing a trace because it was missing a field would bias the sample in a
    direction nobody chose."""
    chosen = sample([{"steps": 3}], policy=STRATIFIED)
    assert chosen["kept"] == 1


# --- the bias is recorded and reversible ------------------------------------


def test_a_stratified_sample_announces_that_it_is_biased() -> None:
    chosen = sample(traces(500))
    assert chosen["is_biased"] is True
    assert "biased on purpose" in chosen["statement"]


def test_the_raw_sample_rate_is_wildly_wrong_and_the_estimate_is_not() -> None:
    """The demonstration this whole module exists for.

    A 2% population failure rate reads as ~70% in a stratified sample that keeps
    every error. Reporting that number would be reporting a property of the
    sampling policy.
    """
    population = traces(1000, failure_every=50)  # exactly 2%
    chosen = sample(population)
    estimate = estimate_rate(chosen, chosen["traces"])

    assert estimate["raw_sample_failure_rate"] > 0.5
    assert estimate["estimated_population_failure_rate"] == pytest.approx(0.02, abs=0.005)


def test_each_kept_trace_says_how_many_it_stands_for() -> None:
    chosen = sample(traces(1000))
    estimate = estimate_rate(chosen, chosen["traces"])
    clean = next(row for row in estimate["by_stratum"] if row["stratum"] == CLEAN)
    assert clean["each_stands_for"] > 10, "a 1% stratum's traces each stand for ~100"
    errored = next(row for row in estimate["by_stratum"] if row["stratum"] == ERRORED)
    assert errored["each_stands_for"] == pytest.approx(1.0), (
        "a fully-kept stratum stands for itself"
    )


def test_a_thin_stratum_is_flagged_rather_than_averaged_in_silently() -> None:
    """A stratum sampled down to three traces contributes an estimate with an
    interval wide enough to swallow the answer."""
    chosen = sample(traces(200))
    estimate = estimate_rate(chosen, chosen["traces"])
    assert estimate["thin_strata"]
    assert "wide guess" in estimate["statement"]


def test_the_correction_uses_the_realised_rate_not_the_requested_one() -> None:
    """With a small population they differ, and using the requested rate would
    project a sample that was never taken."""
    chosen = sample(traces(37))
    assert chosen["realised_rate"][ERRORED] == pytest.approx(1.0)
    assert chosen["realised_rate"][CLEAN] != 0.01 or chosen["kept_by_stratum"].get(CLEAN, 0) == 0


def test_nothing_scored_is_unmeasurable_rather_than_zero() -> None:
    estimate = estimate_rate(sample(traces(100)), [])
    assert estimate["measurable"] is False


def test_every_stratum_says_why_it_is_sampled_the_way_it_is() -> None:
    for stratum in sample(traces(10))["strata"]:
        assert stratum["why"], stratum["name"]


# --- the CLI ----------------------------------------------------------------


def test_the_cli_writes_the_policy_beside_the_sample(tmp_path: Path, capsys) -> None:
    """A kept subset on its own is a file nobody can correct for later."""
    from tooltrace.cli.main import main

    source = tmp_path / "traces.jsonl"
    source.write_text(
        "\n".join(json.dumps(t) for t in traces(200)),
        encoding="utf-8",
    )
    out = tmp_path / "kept.jsonl"
    assert main(["sample", "--source", str(source), "--out", str(out), "--json"]) == 0
    capsys.readouterr()

    assert out.is_file()
    policy = json.loads(out.with_suffix(out.suffix + ".policy.json").read_text(encoding="utf-8"))
    assert policy["policy"] == STRATIFIED
    assert "realised_rate" in policy
    assert "traces" not in policy, "the policy file must not duplicate the sample"


def test_the_cli_refuses_a_missing_file(capsys) -> None:
    from tooltrace.cli.main import main

    assert main(["sample", "--source", "no-such-file.jsonl"]) != 0
    assert "no such file" in capsys.readouterr().err


def test_the_cli_refuses_an_empty_file(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    source = tmp_path / "empty.jsonl"
    source.write_text("", encoding="utf-8")
    assert main(["sample", "--source", str(source)]) != 0
    assert "no traces" in capsys.readouterr().err
