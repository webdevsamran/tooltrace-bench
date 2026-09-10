"""Silent decay, error budgets, and turning an incident into a task.

Half of enterprises have shipped an agent that passed internal evaluation and
still caused a customer-facing failure. The gap is usually not a break but a
slide, and the case a success-rate monitor cannot see is the one worth naming:
**accuracy holds while everything else moves**. An agent whose step count doubled
at the same pass rate has changed, and a rate-only alarm reports nothing.

The other half of these tests is about what `promote_trace` refuses to invent. A
production trace does not contain the filesystem it ran against, so a generated
task ships with an empty workspace and a `TODO` for it. A generated task that
*looked* finished would be the worst possible output: it would run, pass, and
test nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from tooltrace.analysis.drift import (
    DRIFTED,
    MIN_WINDOW,
    STABLE,
    compare_windows,
    error_budget,
)
from tooltrace.cli.main import main
from tooltrace.core.models import TraceEvent
from tooltrace.ingest.promote import DRAFT_MARKER, promote_trace, readiness

_STAMP = "2026-09-09T00:00:00+00:00"


def window(n: int, *, success: bool = True, steps: int = 3, wall: float = 100.0, failed: int = 0):
    return [
        {
            "success": success,
            "steps": steps,
            "wall_ms": wall,
            "failed_tool_calls": failed,
            "tool_calls": 2,
        }
        for _ in range(n)
    ]


def verdict_for(report, metric: str) -> str:
    return next(f["verdict"] for f in report["findings"] if f["metric"] == metric)


# --- the case a rate-only monitor cannot see --------------------------------


def test_accuracy_can_hold_while_behaviour_changes() -> None:
    """Silent decay: passes evals, takes twice as long, nothing fires."""
    got = compare_windows(window(30), window(30, steps=7))
    assert verdict_for(got, "success_rate") == STABLE
    assert verdict_for(got, "steps") == DRIFTED
    assert got["silent_decay"] is True
    assert "accuracy-only monitor would report nothing" in got["statement"]


def test_accuracy_moving_too_is_not_silent_decay() -> None:
    got = compare_windows(window(30), window(30, success=False, steps=7))
    assert got["silent_decay"] is False
    assert verdict_for(got, "success_rate") == DRIFTED


def test_an_unchanged_agent_is_stable_on_every_metric() -> None:
    """A monitor that fires on noise gets muted, and a muted monitor is worse."""
    got = compare_windows(window(30), window(30))
    assert got["drifted"] == []
    assert "No metric moved" in got["statement"]


def test_a_move_too_small_to_matter_is_stable() -> None:
    got = compare_windows(window(40, wall=100.0), window(40, wall=104.0))
    assert verdict_for(got, "wall_ms") == STABLE
    assert "below the" in next(f["note"] for f in got["findings"] if f["metric"] == "wall_ms")


def test_overlapping_intervals_are_not_drift() -> None:
    """The conservative reading, and the right one for a monitor."""
    mixed_before = [*window(15), *window(15, success=False)]
    mixed_after = [*window(14), *window(16, success=False)]
    got = compare_windows(mixed_before, mixed_after)
    assert verdict_for(got, "success_rate") == STABLE


def test_small_windows_cannot_support_a_drift_claim() -> None:
    got = compare_windows(window(3), window(3, steps=99))
    assert got["measurable"] is False
    assert str(MIN_WINDOW) in got["reason"]
    assert got["findings"] == []


def test_a_perfect_window_does_not_make_the_next_one_look_like_drift() -> None:
    """A bootstrap over all-successes collapses to a zero-width interval.

    Wilson does not, which is why proportions use it here.
    """
    got = compare_windows(window(30), window(30))
    row = next(f for f in got["findings"] if f["metric"] == "success_rate")
    assert row["verdict"] == STABLE


def test_it_watches_more_than_accuracy() -> None:
    got = compare_windows(window(30), window(30))
    assert {f["metric"] for f in got["findings"]} >= {
        "success_rate",
        "steps",
        "wall_ms",
        "failed_tool_calls",
    }


# --- error budgets ----------------------------------------------------------


def test_an_slo_becomes_a_number_of_failures() -> None:
    """ "99% reliability" is unactionable; "one failure of budget" is a decision."""
    got = error_budget(window(100), objective=0.99)
    assert got["budget"] == pytest.approx(1.0)
    assert got["remaining"] == pytest.approx(1.0)
    assert got["exhausted"] is False


def test_going_over_reports_how_far_over() -> None:
    """Clamping to zero erases the difference between "at the limit" and "past it"."""
    runs = [*window(97), *window(3, success=False)]
    got = error_budget(runs, objective=0.99)
    assert got["remaining"] < 0
    assert got["exhausted"] is True


def test_a_small_window_says_it_cannot_establish_the_objective() -> None:
    """The interval straddles the objective, so the window settles nothing."""
    got = error_budget(window(10), objective=0.99)
    assert got["objective_is_within_interval"] is True
    assert "cannot establish whether the objective is met" in got["statement"]


def test_a_large_window_can_exclude_the_objective() -> None:
    runs = [*window(50), *window(50, success=False)]
    got = error_budget(runs, objective=0.99)
    assert got["objective_is_within_interval"] is False


def test_an_empty_window_is_not_measurable() -> None:
    assert error_budget([], objective=0.99)["measurable"] is False


def test_a_nonsense_objective_is_refused() -> None:
    assert error_budget(window(10), objective=99)["measurable"] is False
    assert error_budget(window(10), objective=0)["measurable"] is False


# --- promoting a trace into a task ------------------------------------------


def trace(*calls: tuple[str, str, dict]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    seq = 1
    for tool, status, args in calls:
        events.append(
            TraceEvent(
                seq=seq, timestamp=_STAMP, type="tool_request", payload={"tool": tool, "args": args}
            )
        )
        events.append(
            TraceEvent(
                seq=seq + 1,
                timestamp=_STAMP,
                type="tool_result",
                payload={"tool": tool, "status": status},
            )
        )
        seq += 2
    return events


def test_it_encodes_the_trajectory() -> None:
    task = promote_trace(
        trace(
            ("read_file", "ok", {"path": "a.txt"}),
            ("write_file", "ok", {"path": "b.txt", "content": "x"}),
        ),
        task_id="regression/inc",
    )
    match = next(a for a in task["assertions"] if a["type"] == "tool_call_match")
    assert [e["tool"] for e in match["params"]["expected"]] == ["read_file", "write_file"]


def test_it_records_argument_shapes_not_values() -> None:
    """Pinning the exact paths would only ever match the one incident."""
    task = promote_trace(trace(("read_file", "ok", {"path": "a.txt", "lines": 5})), task_id="r/i")
    args = next(a for a in task["assertions"] if a["type"] == "tool_call_match")["params"][
        "expected"
    ][0]["args"]
    assert args == {"path": "string", "lines": "number"}
    assert "a.txt" not in json.dumps(task)


def test_it_refuses_to_invent_a_workspace() -> None:
    """A production trace does not contain the filesystem it ran against."""
    task = promote_trace(trace(("read_file", "ok", {"path": "a"})), task_id="r/i")
    assert task["starting_workspace"] == {}
    assert any("starting_workspace" in todo for todo in task["metadata"]["todos"])


def test_it_refuses_to_invent_a_correctness_assertion() -> None:
    task = promote_trace(trace(("read_file", "ok", {"path": "a"})), task_id="r/i")
    assert all(
        a["type"] in {"tool_call_match", "tools_used", "no_failed_calls", "tool_call_count"}
        for a in task["assertions"]
    )
    assert any("correctness assertion" in todo for todo in task["metadata"]["todos"])


def test_a_clean_trace_gets_no_failure_assertion() -> None:
    """Asserting "no failed calls" on an incident that had none asserts nothing observed."""
    task = promote_trace(trace(("read_file", "ok", {})), task_id="r/i")
    assert not any(a["type"] == "no_failed_calls" for a in task["assertions"])


def test_a_failing_trace_does_get_one() -> None:
    task = promote_trace(trace(("read_file", "error", {})), task_id="r/i")
    assertion = next(a for a in task["assertions"] if a["type"] == "no_failed_calls")
    assert "1 failed call" in assertion["description"]


def test_it_never_claims_to_reproduce_the_incident() -> None:
    task = promote_trace(trace(("read_file", "ok", {})), task_id="r/i", incident="INC-1")
    assert "is a judgement for whoever saw the incident" in task["metadata"]["note"]


def test_a_generated_task_is_marked_as_a_draft() -> None:
    """So a draft cannot quietly become part of a published suite."""
    task = promote_trace(trace(("read_file", "ok", {})), task_id="r/i")
    assert task["id"].endswith(DRAFT_MARKER)
    assert task["metadata"]["generated_from"] == "production_trace"


def test_a_fresh_draft_is_never_ready() -> None:
    task = promote_trace(trace(("read_file", "ok", {})), task_id="r/i")
    report = readiness(task)
    assert report["ready"] is False
    assert any("empty directory" in p for p in report["problems"])
    assert any("produced the wrong result would pass" in p for p in report["problems"])


def test_a_finished_task_passes_readiness() -> None:
    task = promote_trace(trace(("read_file", "ok", {})), task_id="r/i")
    task["id"] = "regression/incident-42"
    task["objective"] = "Read the config and correct the port."
    task["starting_workspace"] = {"config.ini": "port = 80"}
    task["assertions"].append(
        {"type": "file_contains", "params": {"path": "config.ini", "text": "port = 8080"}}
    )
    assert readiness(task)["ready"] is True


# --- the CLI ----------------------------------------------------------------


def test_the_drift_command_reports_an_error_budget(capsys) -> None:
    assert main(["drift", "--current", "results", "--objective", "0.99", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_budget"]["measurable"] is True
    # Fourteen runs cannot establish a 99% objective, and it says so.
    assert payload["error_budget"]["objective_is_within_interval"] is True


def test_the_drift_command_needs_something_to_do(capsys) -> None:
    assert main(["drift", "--current", "results"]) != 0
    assert "needs --baseline" in capsys.readouterr().err


def test_the_drift_command_compares_a_directory_with_itself_as_stable(capsys) -> None:
    code = main(["drift", "--current", "results", "--baseline", "results", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    # Fourteen bundles is above MIN_WINDOW, and a set compared with itself has
    # moved on nothing.
    assert payload["drift"]["measurable"] is True
    assert payload["drift"]["drifted"] == []


def test_promote_trace_writes_a_draft(tmp_path: Path, capsys) -> None:
    source = sorted(Path("results").glob("*.tooltrace"))
    if not source:
        pytest.skip("no committed bundles")
    out = tmp_path / "draft.yaml"
    code = main(
        [
            "promote-trace",
            str(source[0] / "trace.jsonl"),
            "--task-id",
            "regression/inc-1",
            "--incident",
            "INC-1",
            "--out",
            str(out),
            "--json",
        ]
    )
    assert code == 0
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert written["id"].endswith(DRAFT_MARKER)
    assert written["starting_workspace"] == {}


def test_promote_trace_refuses_an_empty_trace(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert main(["promote-trace", str(empty), "--task-id", "r/i"]) != 0
    assert "empty" in capsys.readouterr().err
