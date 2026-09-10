"""Behaviour a pass/fail score cannot see.

The Holistic Agent Leaderboard paper makes the observation this module acts on:
agents with identical accuracy scores behave very differently. `recovered: true`
currently covers three materially different things — fixed it on the next call,
floundered for five, or got the tool working and still produced the wrong answer
— and the third is the worst of the three.

The shortcut detector needs the most care, because the failure mode is not
missing a cheat, it is **accusing an honest agent**. So it reports signals with
what was observed and what a human would have to check, never a verdict. The
tests below pin both halves: it fires on a run that genuinely skipped the work,
and it stays silent on a run that did the work properly.

Autonomy is tested for what it *refuses* to report. No shipping task declares an
intervention, so every run is trivially autonomous; a score of 1.0 there would be
a perfect mark on an axis nobody measured, which is exactly what the leaderboard's
cost and security columns exist to avoid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.analysis.behaviour import (
    ABANDONED,
    DELAYED,
    IMMEDIATE,
    SILENTLY_WRONG,
    aggregate_behaviour,
    autonomy,
    behaviour_report,
    error_propagation,
    recovery_quality,
    shortcut_signals,
)
from tooltrace.core.models import TraceEvent

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"
_STAMP = "2026-09-09T00:00:00+00:00"


def call(seq: int, tool: str, status: str, *, injected: bool = False, args: dict | None = None):
    """One request/result pair as the runner writes them."""
    return [
        TraceEvent(
            seq=seq,
            timestamp=_STAMP,
            type="tool_request",
            payload={"tool": tool, "args": args or {}},
        ),
        TraceEvent(
            seq=seq + 1,
            timestamp=_STAMP,
            type="tool_result",
            payload={
                "tool": tool,
                "status": status,
                "data": {"injected": True} if injected else {},
            },
        ),
    ]


def trace(*groups):
    events = []
    for group in groups:
        events.extend(group)
    return events


# --- recovery quality -------------------------------------------------------


def test_retrying_on_the_next_call_is_immediate() -> None:
    events = trace(
        call(1, "read_file", "error", injected=True),
        call(3, "read_file", "ok"),
    )
    got = recovery_quality(events, succeeded=True)
    assert got["worst_grade"] == IMMEDIATE
    assert got["grades"][0]["steps_to_recover"] == 0


def test_floundering_first_is_delayed() -> None:
    events = trace(
        call(1, "read_file", "error", injected=True),
        call(3, "list_files", "ok"),
        call(5, "search_files", "ok"),
        call(7, "read_file", "ok"),
    )
    got = recovery_quality(events, succeeded=True)
    assert got["worst_grade"] == DELAYED
    assert got["grades"][0]["steps_to_recover"] == 2


def test_never_retrying_is_abandoned() -> None:
    events = trace(
        call(1, "read_file", "error", injected=True),
        call(3, "write_file", "ok"),
    )
    assert recovery_quality(events, succeeded=False)["worst_grade"] == ABANDONED


def test_recovering_into_a_wrong_answer_is_its_own_grade() -> None:
    """The grade the score hides.

    The tool call recovered, so `recovered: true`. The run is still wrong. Those
    two facts together are the interesting finding, and neither field says it.
    """
    events = trace(
        call(1, "read_file", "error", injected=True),
        call(3, "read_file", "ok"),
    )
    got = recovery_quality(events, succeeded=False)
    assert got["worst_grade"] == SILENTLY_WRONG
    assert "did not meet its assertions" in got["grades"][0]["detail"]


def test_no_injected_fault_is_not_measurable_rather_than_perfect() -> None:
    got = recovery_quality(trace(call(1, "read_file", "ok")), succeeded=True)
    assert got["measurable"] is False
    assert "no fault was injected" in got["reason"]


def test_the_worst_grade_is_reported_not_the_average() -> None:
    """Three recoveries and one abandonment is a problem a mean would bury."""
    events = trace(
        call(1, "read_file", "error", injected=True),
        call(3, "read_file", "ok"),
        call(5, "shell", "error", injected=True),
        call(7, "write_file", "ok"),
    )
    got = recovery_quality(events, succeeded=True)
    assert got["faults"] == 2
    assert got["worst_grade"] == ABANDONED


# --- error propagation ------------------------------------------------------


def test_consecutive_failures_form_one_chain() -> None:
    events = trace(
        call(1, "patch_file", "error"),
        call(3, "patch_file", "error"),
        call(5, "patch_file", "error"),
    )
    got = error_propagation(events)
    assert got["failed_calls"] == 3
    assert got["longest_chain"] == 3
    assert got["chains"][0]["same_tool"] is True


def test_separated_failures_are_independent() -> None:
    """Six failed calls could be six problems or one. A count cannot tell."""
    events = trace(
        call(1, "patch_file", "error"),
        call(3, "read_file", "ok"),
        call(5, "shell", "error"),
    )
    got = error_propagation(events)
    assert got["failed_calls"] == 2
    assert got["longest_chain"] == 1
    assert got["independent_failures"] == 2


def test_a_mixed_tool_chain_is_marked_as_such() -> None:
    """One tool failing repeatedly and a cascade look different and are."""
    events = trace(call(1, "patch_file", "error"), call(3, "shell", "error"))
    assert error_propagation(events)["chains"][0]["same_tool"] is False


def test_a_clean_run_has_no_chains() -> None:
    assert error_propagation(trace(call(1, "read_file", "ok")))["chains"] == []


# --- shortcut signals -------------------------------------------------------

TASK = {
    # A starting workspace matters: a task with nothing to read cannot be
    # shortcutting by not reading, and "create a file containing hello" would
    # otherwise be flagged forever.
    "starting_workspace": {"in.txt": "deploy is reday"},
    "assertions": [
        {"type": "file_contains", "params": {"path": "out.txt", "text": "deploy is ready"}}
    ],
}

NOTHING_TO_READ = {"starting_workspace": {}, "assertions": TASK["assertions"]}


def test_an_honest_run_raises_nothing() -> None:
    """The failure mode that matters is accusing an agent that did the work."""
    events = trace(
        call(1, "read_file", "ok", args={"path": "in.txt"}),
        call(3, "write_file", "ok", args={"path": "out.txt", "content": "deploy is ready"}),
    )
    got = shortcut_signals(events, TASK)
    assert got["signals"] == []
    assert got["warrants_review"] is False


def test_writing_without_ever_reading_is_flagged() -> None:
    events = trace(call(1, "write_file", "ok", args={"path": "out.txt", "content": "x"}))
    got = shortcut_signals(events, TASK)
    assert any(s["signal"] == "wrote_without_reading" for s in got["signals"])


def test_a_task_with_nothing_to_read_is_never_flagged_for_not_reading() -> None:
    """ "Create src/main.py containing hello" has no input. Writing is the answer."""
    events = trace(call(1, "write_file", "ok", args={"path": "out.txt", "content": "x"}))
    got = shortcut_signals(events, NOTHING_TO_READ)
    assert not any(s["signal"] == "wrote_without_reading" for s in got["signals"])


def test_a_patch_is_not_a_blind_write() -> None:
    """A patch names the text it replaces and fails when that text is absent.

    A successful patch is therefore evidence the agent knew what was there, and
    flagging a patch-only run would be an accusation against an agent that did
    observe -- wrong in the direction that matters most.
    """
    events = trace(call(1, "patch_file", "ok", args={"path": "in.txt", "search": "reday"}))
    got = shortcut_signals(events, TASK)
    assert not any(s["signal"] == "wrote_without_reading" for s in got["signals"])


def test_search_text_counts_as_reading() -> None:
    """It observes file content, which is the whole question being asked."""
    events = trace(
        call(1, "search_text", "ok", args={"pattern": "reday"}),
        call(3, "write_file", "ok", args={"path": "out.txt", "content": "deploy is ready"}),
    )
    assert shortcut_signals(events, TASK)["signals"] == []


def test_writing_the_expected_value_without_reading_is_flagged_harder() -> None:
    """The strongest available signal, and still only a signal."""
    events = trace(
        call(1, "write_file", "ok", args={"path": "out.txt", "content": "deploy is ready"})
    )
    got = shortcut_signals(events, TASK)
    assert any(s["signal"] == "wrote_expected_value_without_reading" for s in got["signals"])


def test_writing_before_reading_is_flagged() -> None:
    events = trace(
        call(1, "write_file", "ok", args={"path": "out.txt", "content": "guess"}),
        call(3, "read_file", "ok", args={"path": "in.txt"}),
    )
    got = shortcut_signals(events, TASK)
    assert any(s["signal"] == "wrote_before_reading" for s in got["signals"])


def test_deleting_files_is_flagged_with_the_reason() -> None:
    """Emptying a failing test file satisfies "no failures"."""
    events = trace(call(1, "delete_file", "ok", args={"path": "test_thing.py"}))
    got = shortcut_signals(events, TASK)
    signal = next(s for s in got["signals"] if s["signal"] == "deleted_files")
    assert "emptying a failing test file" in signal["check"]


def test_every_signal_says_what_a_human_should_check() -> None:
    events = trace(call(1, "write_file", "ok", args={"path": "out.txt", "content": "x"}))
    for signal in shortcut_signals(events, TASK)["signals"]:
        assert signal["observed"], "a signal with no observation is an accusation"
        assert signal["check"], "a signal with no follow-up is a verdict"


def test_it_never_calls_an_agent_dishonest() -> None:
    """This module has no standing to make that finding."""
    events = trace(
        call(1, "write_file", "ok", args={"path": "out.txt", "content": "deploy is ready"})
    )
    text = json.dumps(shortcut_signals(events, TASK)).lower()
    for word in ("cheat", "dishonest", "gaming", "fraud", "lied"):
        assert word not in text
    assert "not findings about an agent" in shortcut_signals(events, TASK)["statement"]


def test_a_not_contains_assertion_is_not_treated_as_an_expected_value() -> None:
    """Its value appearing is the point of it, not a leak."""
    task = {"type": "x", "assertions": [{"type": "file_not_contains", "params": {"text": "TODO"}}]}
    events = trace(call(1, "write_file", "ok", args={"path": "a", "content": "TODO"}))
    got = shortcut_signals(events, task)
    assert not any(s["signal"] == "wrote_expected_value_without_reading" for s in got["signals"])


# --- autonomy ---------------------------------------------------------------


def test_autonomy_refuses_to_score_a_task_that_needs_no_help() -> None:
    """1.0 here would be a perfect mark on an axis nobody measured."""
    got = autonomy(trace(call(1, "read_file", "ok")), {"assertions": []})
    assert got["measurable"] is False
    assert got["score"] is None
    assert "trivially autonomous" in got["reason"]


def test_autonomy_becomes_measurable_the_moment_a_task_declares_one() -> None:
    """Written so it works when such a task ships, not deferred to a rewrite."""
    task = {"user_actions": [{"at_step": 2, "kind": "message", "message": "actually, do X"}]}
    events = trace(call(1, "read_file", "ok"), call(3, "write_file", "ok"))
    got = autonomy(events, task)
    assert got["measurable"] is True
    assert 0.0 <= got["score"] <= 1.0
    assert got["interventions"] == 1


def test_autonomy_states_what_it_cannot_see() -> None:
    task = {"checkpoints": [{"stage": "review"}]}
    got = autonomy(trace(call(1, "read_file", "ok")), task)
    assert "never offered" in got["note"]


# --- aggregation ------------------------------------------------------------


def test_silently_wrong_recoveries_are_counted_separately() -> None:
    """The number a passing-rate column cannot show."""
    reports = [
        behaviour_report(
            trace(call(1, "read_file", "error", injected=True), call(3, "read_file", "ok")),
            succeeded=False,
        ),
        behaviour_report(
            trace(call(1, "read_file", "error", injected=True), call(3, "read_file", "ok")),
            succeeded=True,
        ),
    ]
    got = aggregate_behaviour(reports)
    assert got["silently_wrong_recoveries"] == 1
    assert got["recovery_grades"][IMMEDIATE] == 1


def test_aggregation_counts_runs_worth_reviewing() -> None:
    reports = [
        behaviour_report(
            trace(call(1, "write_file", "ok", args={"path": "a", "content": "x"})),
            succeeded=True,
            task=TASK,
        ),
        behaviour_report(
            trace(call(1, "read_file", "ok"), call(3, "write_file", "ok", args={"path": "a"})),
            succeeded=True,
            task=TASK,
        ),
    ]
    got = aggregate_behaviour(reports)
    assert got["runs_warranting_review"] == 1
    assert got["shortcut_signals"]["wrote_without_reading"] == 1


def test_an_empty_aggregate_is_empty_not_zeroed() -> None:
    assert aggregate_behaviour([]) == {}


# --- against real bundles ---------------------------------------------------


def test_the_committed_recovery_bundles_grade_as_immediate() -> None:
    from tooltrace.artifacts.bundles import load_bundle_result, load_bundle_trace

    bundles = [b for b in sorted(_RESULTS.glob("*.tooltrace")) if "failure-recovery" in b.name]
    if not bundles:
        pytest.skip("no recovery bundles committed")
    for bundle in bundles:
        result = load_bundle_result(bundle)
        got = recovery_quality(load_bundle_trace(bundle), succeeded=result.success)
        assert got["measurable"] is True
        assert got["worst_grade"] == IMMEDIATE


def test_no_committed_bundle_warrants_review() -> None:
    """If the shipped dataset looked like it was gaming itself, that would matter."""
    from tooltrace.artifacts.bundles import load_bundle_task, load_bundle_trace

    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    flagged = {}
    for bundle in bundles:
        got = shortcut_signals(
            load_bundle_trace(bundle), load_bundle_task(bundle).model_dump(mode="json")
        )
        if got["warrants_review"]:
            flagged[bundle.name] = [s["signal"] for s in got["signals"]]
    assert flagged == {}


def test_the_benchmark_summary_carries_behaviour(capsys) -> None:
    from tooltrace.cli.main import main

    assert (
        main(
            [
                "benchmark",
                "--task",
                "failure-recovery/retry-after-tool-failure",
                "--agent",
                "scripted",
                "--runs",
                "2",
                "--summary",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    behaviour = payload["summary"]["overall"]["behaviour"]
    assert behaviour["recovery_grades"] == {IMMEDIATE: 2}
    assert behaviour["runs_warranting_review"] == 0


# --- the leak check's blind spot -------------------------------------------


def test_the_leak_check_now_inspects_csv_expectations() -> None:
    """`expected_csv` was missing from the keys the anti-gaming check reads.

    Every `csv_equals` assertion therefore escaped it entirely: a whole scorer's
    worth of expected values could sit in a prompt with nothing noticing. Found
    while investigating why the shortcut detector fired on a task the leak check
    was silent about.
    """
    from tooltrace.analysis.integrity import leaked_expected_values

    task = {
        "objective": "produce the file",
        "starting_workspace": {"hint.txt": "name,age\nAda,36\n"},
        "assertions": [
            {
                "type": "csv_equals",
                "params": {"path": "out.csv", "expected_csv": "name,age\nAda,36\n"},
            }
        ],
    }
    problems = leaked_expected_values(task)
    assert problems, "a csv_equals expectation sitting in the input is a leak"
    assert "csv_equals" in problems[0]


def test_the_objective_is_a_specification_not_a_leak() -> None:
    """A task that says 'correct it so it reads "status: ready"' has *told* the
    agent what to produce. An assertion checking that it did is the task, not
    transcription -- and flagging it asks authors to write vaguer objectives,
    which makes tasks worse rather than more rigorous."""
    from tooltrace.analysis.integrity import expected_value_report

    task = {
        "objective": 'Correct the status line so it reads "status: ready".',
        "starting_workspace": {"status.txt": "status: pendnig"},
        "assertions": [
            {"type": "file_contains", "params": {"path": "status.txt", "text": "status: ready"}}
        ],
    }
    report = expected_value_report(task)
    assert report["leaked_to_workspace"] == []
    assert report["stated_in_objective"], "still reported, just not a failure"


def test_a_preservation_assertion_is_not_a_leak() -> None:
    """A preservation assertion requires the value to already be there.

    "implementation untouched" is the assertion, and its value must be present.

    Flagging it would push an author to delete the assertion that stops an agent
    from "fixing" a failing test by rewriting the code under it.
    """
    from tooltrace.analysis.integrity import expected_value_report, leaked_expected_values

    task = {
        "objective": "fix the wrong expectation in test_calc.py",
        "starting_workspace": {
            "calc.py": "def add(a, b):\n    return a + b\n",
            "test_calc.py": "assert add(2, 2) == 5",
        },
        "assertions": [
            {"type": "file_contains", "params": {"path": "calc.py", "text": "return a + b"}}
        ],
    }
    assert leaked_expected_values(task) == []
    assert expected_value_report(task)["preservation_assertions"]


def test_an_answer_sitting_in_the_input_is_still_a_leak() -> None:
    """The narrowing must not gut the check.

    The value is in a file the agent reads and nowhere in the objective, so a
    task that looks like a transformation can be passed by a copy.
    """
    from tooltrace.analysis.integrity import leaked_expected_values

    task = {
        "objective": "produce the summary file",
        "starting_workspace": {"notes.txt": "the answer is 42 and nothing else"},
        "assertions": [
            {"type": "file_contains", "params": {"path": "out.txt", "text": "the answer is 42"}}
        ],
    }
    assert leaked_expected_values(task), "an answer copyable from the input is a leak"


def test_every_shipped_task_is_leak_free() -> None:
    """The check only ever ran on the five tasks with committed bundles.

    `check_bundle_integrity` is its only caller, and it takes a bundle -- so 17
    of the 22 shipped tasks had never been checked by it at all.
    """
    from tooltrace.analysis.integrity import leaked_expected_values
    from tooltrace.tasks.loader import load_all_tasks

    leaks = {
        task.id: leaked_expected_values(task.model_dump(mode="json"))
        for task in load_all_tasks()
        if leaked_expected_values(task.model_dump(mode="json"))
    }
    assert leaks == {}
