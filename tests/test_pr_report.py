"""A PR gate that fires on noise gets switched off, so this one has to be right.

`check_regression` compares two **single-run** bundles. For latency on a
deterministic task that is defensible. For a success rate it is not: one run is
one Bernoulli draw, and "the score dropped from 1.0 to 0.0" describes a coin
landing differently. A gate built on that either blocks pull requests at random
or gets disabled — and both are worse than no gate.

The four-state verdict is what these tests mostly exercise, and the fourth state
is the load-bearing one. Without `inconclusive`, "no regression" covers both "we
checked" and "we could not tell", so a green check on 3 runs would mean the same
thing as a green check on 300. With it, the other three verdicts mean something.

The other rule under test: **only an established regression fails the build.**
Failing on inconclusive would make the gate a function of the caller's compute
budget rather than of whether the code got worse.
"""

from __future__ import annotations

import json
from pathlib import Path

from tooltrace.analysis.pr_report import (
    IMPROVED,
    INCONCLUSIVE,
    NO_CHANGE,
    REGRESSED,
    cohort_problems,
    compare_samples,
    render_markdown,
)
from tooltrace.cli.main import main


def runs(n: int, *, successes: int | None = None, wall: float = 10.0, steps: int = 3) -> list[dict]:
    passing = n if successes is None else successes
    return [
        {
            "success": i < passing,
            "score_total": 1.0 if i < passing else 0.0,
            "steps": steps,
            "failed_tool_calls": 0,
            "wall_ms": wall,
        }
        for i in range(n)
    ]


def verdict_for(report, metric: str) -> str:
    return next(v.verdict for v in report.verdicts if v.metric == metric)


# --- the case the old gate got wrong ----------------------------------------


def test_one_run_each_side_is_never_a_regression() -> None:
    """The precise defect: a single Bernoulli draw called a regression."""
    report = compare_samples(runs(1, successes=1), runs(1, successes=0))
    assert report.regressed is False
    assert verdict_for(report, "success_rate") == INCONCLUSIVE


def test_a_small_sample_with_no_change_is_inconclusive_not_clean() -> None:
    """Ten perfect runs against ten perfect runs still permit a 27-point drop."""
    report = compare_samples(runs(10), runs(10))
    assert verdict_for(report, "success_rate") == INCONCLUSIVE
    assert report.regressed is False


def test_a_large_sample_with_no_change_says_so_positively() -> None:
    report = compare_samples(runs(400), runs(400))
    assert verdict_for(report, "success_rate") == NO_CHANGE


# --- a real regression is caught --------------------------------------------


def test_a_large_real_drop_is_a_regression() -> None:
    report = compare_samples(runs(200, successes=200), runs(200, successes=100))
    assert verdict_for(report, "success_rate") == REGRESSED
    assert report.regressed is True


def test_a_large_real_improvement_is_not_a_regression() -> None:
    report = compare_samples(runs(200, successes=100), runs(200, successes=200))
    assert verdict_for(report, "success_rate") == IMPROVED
    assert report.regressed is False


def test_a_small_drop_in_a_small_sample_is_not_called_a_regression() -> None:
    """The 2-point move this whole feature exists to stop blocking on."""
    report = compare_samples(runs(50, successes=50), runs(50, successes=49))
    assert verdict_for(report, "success_rate") != REGRESSED
    assert report.regressed is False


# --- direction is respected per metric --------------------------------------


def test_more_steps_is_worse_and_fewer_is_better() -> None:
    worse = compare_samples(runs(200, steps=3), runs(200, steps=9))
    assert verdict_for(worse, "steps") == REGRESSED

    better = compare_samples(runs(200, steps=9), runs(200, steps=3))
    assert verdict_for(better, "steps") == IMPROVED


def test_a_higher_score_is_better_not_worse() -> None:
    report = compare_samples(runs(200, successes=100), runs(200, successes=200))
    assert verdict_for(report, "score") == IMPROVED


# --- latency's threshold is relative ----------------------------------------


def test_latency_uses_a_share_of_the_baseline_not_an_absolute_figure() -> None:
    """5 ms is nothing on a 4-second task and everything on a 6 ms one.

    A fixed absolute threshold would make latency the one metric that can never
    be inconclusive, which is backwards: it is the noisiest of the five.
    """
    slow = compare_samples(runs(200, wall=4000.0), runs(200, wall=4005.0))
    assert verdict_for(slow, "wall_ms") == NO_CHANGE

    fast = compare_samples(runs(200, wall=6.0), runs(200, wall=11.0))
    assert verdict_for(fast, "wall_ms") == REGRESSED


def test_a_certain_but_negligible_change_is_not_a_regression() -> None:
    """Statistical significance is not practical significance.

    These fixtures have zero run-to-run variance, so a +5 ms shift on a 4-second
    baseline is *certain* -- the interval excludes zero with no overlap at all.
    It is also a 0.125% change. Failing a pull request on that is exactly the
    behaviour that gets a reliability gate switched off, so both questions have
    to be answered yes: is the change real, and is it large enough to matter.
    """
    report = compare_samples(runs(200, wall=4000.0), runs(200, wall=4005.0))
    row = next(v for v in report.verdicts if v.metric == "wall_ms")
    assert row.delta_ci is not None
    assert row.delta_ci[0] > 0, "the interval really does exclude zero"
    assert row.verdict == NO_CHANGE
    assert "not worth blocking on" in row.note
    assert report.regressed is False


def test_a_certain_and_material_change_is_still_a_regression() -> None:
    """The threshold must not become a way to ignore real regressions."""
    report = compare_samples(runs(200, successes=200), runs(200, successes=100))
    assert verdict_for(report, "success_rate") == REGRESSED


# --- the interval is on the difference --------------------------------------


def test_the_interval_is_on_the_difference_not_on_either_side() -> None:
    """Two overlapping per-side intervals do not imply the difference includes 0.

    Reporting per-side intervals and leaving the reader to compare them by eye is
    the most common way to get this wrong, so the difference is computed once.
    """
    report = compare_samples(runs(200, successes=200), runs(200, successes=100))
    row = next(v for v in report.verdicts if v.metric == "success_rate")
    assert row.delta_ci is not None
    low, high = row.delta_ci
    assert low < row.delta < high
    assert high < 0, "a real drop's interval must sit entirely below zero"


def test_a_perfect_sample_does_not_get_a_zero_width_interval() -> None:
    """A bootstrap over identical values collapses; Wilson does not.

    "The rate is exactly 1.0 with no uncertainty" is the most misleading thing
    this module could produce, and it is what bootstrapping a proportion of all
    ones would produce.
    """
    report = compare_samples(runs(10), runs(10))
    row = next(v for v in report.verdicts if v.metric == "success_rate")
    assert row.delta_ci is not None
    assert row.delta_ci[0] < 0 < row.delta_ci[1]


# --- cohort safety ----------------------------------------------------------


def test_a_different_task_set_is_refused_not_annotated() -> None:
    """Comparing different measurements and blaming the code is worse than nothing."""
    problems = cohort_problems({"task_ids": ["a"]}, {"task_ids": ["a", "b"]})
    assert problems and "task set differs" in problems[0]


def test_a_different_compatibility_key_is_refused() -> None:
    problems = cohort_problems({"compatibility_key": "v1"}, {"compatibility_key": "v2"})
    assert problems and "compatibility key" in problems[0]


def test_identical_cohorts_have_no_problems() -> None:
    meta = {"compatibility_key": "v1", "task_ids": ["a", "b"]}
    assert cohort_problems(meta, dict(meta)) == []


def test_missing_metadata_does_not_invent_a_problem() -> None:
    assert cohort_problems({}, {"task_ids": ["a"]}) == []


# --- the rendered comment ---------------------------------------------------


def test_the_comment_distinguishes_checked_from_could_not_tell() -> None:
    small = render_markdown(compare_samples(runs(10), runs(10)))
    assert "not every metric could be checked" in small

    large = render_markdown(compare_samples(runs(400), runs(400)))
    assert "large enough to say so" in large


def test_a_regression_leads_the_comment() -> None:
    markdown = render_markdown(compare_samples(runs(200, successes=200), runs(200, successes=100)))
    assert markdown.index("regression the sample supports") < markdown.index("| Metric |")


def test_verdicts_are_words_not_colours() -> None:
    """A comment gets quoted into a terminal, an email digest and a reader."""
    markdown = render_markdown(compare_samples(runs(10), runs(10)))
    assert "inconclusive" in markdown
    for symbol in ("🔴", "🟢", "⚠️", "✅"):
        assert symbol not in markdown


def test_the_comment_explains_each_inconclusive_row() -> None:
    markdown = render_markdown(compare_samples(runs(10), runs(10)))
    assert "more runs are needed" in markdown


def test_the_comment_states_what_the_interval_is_on() -> None:
    markdown = render_markdown(compare_samples(runs(10), runs(10)))
    assert "on the **difference**" in markdown


def test_the_comment_is_ascii_only() -> None:
    """It is printed to a console as well as posted; a mangled table is useless."""
    render_markdown(compare_samples(runs(10), runs(10))).encode("ascii")


def test_incomparable_sets_are_named_at_the_top() -> None:
    report = compare_samples(runs(10), runs(10))
    report.incomparable.append("task set differs: ['a'] vs ['b']")
    markdown = render_markdown(report)
    assert markdown.index("Not compared") < markdown.index("| Metric |")


# --- the CLI ----------------------------------------------------------------


def _bundles(tmp_path: Path, name: str, runs_count: int) -> Path:
    out = tmp_path / name
    assert (
        main(
            [
                "benchmark",
                "--task",
                "file-editing/fix-config-typo",
                "--agent",
                "scripted",
                "--runs",
                str(runs_count),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return out


#: Everything except wall-clock. See the test below for why this is not
#: cheating: the two arms here run the same agent on the same task, so any
#: latency difference between them is a fact about the machine.
BEHAVIOURAL = "success_rate,score,steps,failed_tool_calls"


def test_the_cli_reports_and_exits_zero_without_an_established_regression(
    tmp_path: Path, capsys
) -> None:
    baseline = _bundles(tmp_path, "base", 3)
    current = _bundles(tmp_path, "curr", 3)
    capsys.readouterr()
    code = main(
        [
            "pr-report",
            "--baseline",
            str(baseline),
            "--current",
            str(current),
            "--metrics",
            BEHAVIOURAL,
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, "an inconclusive comparison must not block a pull request"
    assert payload["regressed"] is False
    assert payload["markdown"].startswith("### Agent reliability")


def test_wall_clock_is_excluded_here_because_it_is_not_a_property_of_the_agent() -> None:
    """This test was flaky, and the flake was telling the truth.

    Both arms above run the identical scripted agent on the identical task, so
    every behavioural metric is identical by construction. `wall_ms` is not: it
    is wall-clock on whatever machine happened to run it, and under a loaded
    test suite three runs against three runs can differ by more than the 20%
    that `pr-report` treats as worth blocking on. The report was right; the
    assertion was wrong.

    That is also why `--metrics` exists. A team on a shared CI runner would hit
    this on real pull requests, switch the gate off, and lose the four metrics
    that *were* worth gating on. Narrowing a gate beats losing it.
    """
    from tooltrace.analysis.pr_report import METRICS

    assert set(BEHAVIOURAL.split(",")) == set(METRICS) - {"wall_ms"}


def test_the_cli_writes_the_comment_to_a_file(tmp_path: Path, capsys) -> None:
    baseline = _bundles(tmp_path, "base", 2)
    current = _bundles(tmp_path, "curr", 2)
    out = tmp_path / "comment.md"
    capsys.readouterr()
    main(
        [
            "pr-report",
            "--baseline",
            str(baseline),
            "--current",
            str(current),
            "--out",
            str(out),
            "--json",
        ]
    )
    assert out.is_file()
    assert "| Metric |" in out.read_text(encoding="utf-8")


def test_the_cli_needs_bundles_on_both_sides(tmp_path: Path, capsys) -> None:
    baseline = _bundles(tmp_path, "base", 2)
    empty = tmp_path / "empty"
    empty.mkdir()
    capsys.readouterr()
    assert main(["pr-report", "--baseline", str(baseline), "--current", str(empty)]) != 0
    assert "needs bundles on both sides" in capsys.readouterr().err
