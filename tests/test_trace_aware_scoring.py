"""Scoring the trajectory, not only the final workspace.

Every one of the fifteen original scorers takes `(params, workspace)` and reads
the end state of the filesystem. That is the right default — it is what lets a
third party recompute a score from a bundle — but it makes an entire class of
question inexpressible. "Did the agent read the file before overwriting it?"
cannot be answered from the file.

The demonstration in `test_a_guesser_passes_the_outcome_and_fails_the_trajectory`
is the whole argument for this project in one assertion: an agent that guesses
the right answer scores 1.0 on the outcome check and still fails, because the
route it took was wrong. A benchmark that only inspected the workspace would
have called that a pass.

The structural matcher is modelled on the Berkeley Function-Calling
Leaderboard's AST approach — name, argument names, argument types, nothing
executed. It is deliberately *not* the headline metric here; see
`docs/tool-call-structure.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tooltrace.core.models import TraceEvent
from tooltrace.runners.runner import TaskRunner
from tooltrace.scoring.composite import score_task
from tooltrace.scoring.trace_scorers import TRACE_SCORERS, match_call
from tooltrace.scoring.trace_view import ToolCall, TraceView
from tooltrace.tasks import load_all_tasks

_TASK_ID = "tool-call-structure/read-before-write"


def _task(task_id: str = _TASK_ID):
    return next(t for t in load_all_tasks() if t.id == task_id)


def _call(tool: str, **args: Any) -> ToolCall:
    return ToolCall(seq=1, tool=tool, args=args)


def _events(*pairs: tuple[str, dict[str, Any], str]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    seq = 1
    for tool, args, status in pairs:
        events.append(
            TraceEvent(
                timestamp="2026-01-01T00:00:00Z",
                seq=seq,
                type="tool_request",
                payload={"tool": tool, "args": args},
            )
        )
        seq += 1
        events.append(
            TraceEvent(
                timestamp="2026-01-01T00:00:00Z",
                seq=seq,
                type="tool_result",
                payload={"tool": tool, "status": status},
            )
        )
        seq += 1
    return events


# --- the view ---------------------------------------------------------------


def test_requests_and_results_become_one_call() -> None:
    view = TraceView.from_events(_events(("read_file", {"path": "a"}, "ok")))
    assert len(view.calls) == 1
    assert view.calls[0].tool == "read_file"
    assert view.calls[0].args == {"path": "a"}
    assert view.calls[0].ok is True


def test_an_unanswered_request_is_dropped_not_assumed_successful() -> None:
    """A truncated trace must not be scored as though the last call worked."""
    events = _events(("read_file", {"path": "a"}, "ok"))
    events.append(
        TraceEvent(
            timestamp="2026-01-01T00:00:00Z",
            seq=99,
            type="tool_request",
            payload={"tool": "write_file", "args": {}},
        )
    )
    view = TraceView.from_events(events)
    assert view.tools_used() == ["read_file"]


# --- structural matching (BFCL-style) ---------------------------------------


def test_an_exact_call_matches() -> None:
    assert (
        match_call(_call("read_file", path="a"), {"tool": "read_file", "args": {"path": "string"}})
        == []
    )


def test_the_wrong_tool_is_reported() -> None:
    assert match_call(_call("read_file", path="a"), {"tool": "write_file"})


def test_a_missing_argument_is_reported() -> None:
    problems = match_call(
        _call("read_file", path="a"), {"tool": "read_file", "args": {"encoding": "string"}}
    )
    assert problems == ["missing argument 'encoding'"]


def test_a_wrong_argument_type_is_reported() -> None:
    problems = match_call(
        _call("read_file", path=7), {"tool": "read_file", "args": {"path": "string"}}
    )
    assert "should be string" in problems[0]


def test_a_boolean_is_not_accepted_as_an_integer() -> None:
    """`bool` subclasses `int` in Python; a structural check must not be fooled."""
    problems = match_call(_call("t", n=True), {"tool": "t", "args": {"n": "integer"}})
    assert problems


def test_an_exact_value_can_be_required() -> None:
    expected = {"tool": "write_file", "args": {"path": {"type": "string", "equals": "a.txt"}}}
    assert match_call(_call("write_file", path="a.txt"), expected) == []
    assert match_call(_call("write_file", path="b.txt"), expected)


def test_a_forbidden_argument_is_reported() -> None:
    expected = {"tool": "shell", "forbidden_args": ["cwd"]}
    assert match_call(_call("shell", cmd="ls"), expected) == []
    assert match_call(_call("shell", cmd="ls", cwd="/"), expected)


def test_a_bare_list_requires_argument_names_only() -> None:
    assert match_call(_call("read_file", path="a"), {"tool": "read_file", "args": ["path"]}) == []
    assert match_call(_call("read_file", path="a"), {"tool": "read_file", "args": ["encoding"]})


# --- the scorers ------------------------------------------------------------


def test_order_is_enforced_when_requested() -> None:
    scorer = TRACE_SCORERS["tool_call_match"]
    view = TraceView.from_events(
        _events(("write_file", {"path": "a"}, "ok"), ("read_file", {"path": "a"}, "ok"))
    )
    params = {
        "ordered": True,
        "expected": [{"tool": "read_file"}, {"tool": "write_file"}],
    }
    assert scorer(params, view).score < 1.0
    assert scorer({**params, "ordered": False}, view).score == 1.0


def test_extra_calls_can_be_forbidden() -> None:
    scorer = TRACE_SCORERS["tool_call_match"]
    view = TraceView.from_events(
        _events(("read_file", {"path": "a"}, "ok"), ("shell", {"cmd": "ls"}, "ok"))
    )
    params = {"expected": [{"tool": "read_file"}], "allow_extra": False}
    outcome = scorer(params, view)
    assert outcome.score == 0.0
    assert "extra calls" in outcome.detail


def test_declaring_no_expectations_scores_zero_rather_than_passing_vacuously() -> None:
    scorer = TRACE_SCORERS["tool_call_match"]
    assert scorer({"expected": []}, TraceView()).score == 0.0


def test_forbidden_tools_are_caught() -> None:
    scorer = TRACE_SCORERS["tools_used"]
    view = TraceView.from_events(_events(("shell", {"cmd": "rm"}, "ok")))
    assert scorer({"forbidden": ["shell"]}, view).score == 0.0
    assert scorer({"required": ["shell"]}, view).score == 1.0


def test_failed_calls_are_counted_against_a_tolerance() -> None:
    scorer = TRACE_SCORERS["no_failed_calls"]
    view = TraceView.from_events(_events(("read_file", {"p": 1}, "error")))
    assert scorer({"allow": 0}, view).score == 0.0
    assert scorer({"allow": 1}, view).score == 1.0


# --- dispatch ---------------------------------------------------------------


def test_a_trace_assertion_without_a_trace_refuses_rather_than_scoring_zero_silently(
    tmp_path: Path,
) -> None:
    """ "We could not look" and "we looked and it failed" are different facts."""
    task = _task()
    score, details = score_task(task, tmp_path, trace=None)
    assert details["read before write"].endswith("which this caller did not supply")
    assert score.components["read before write"] == 0.0


def test_workspace_scorers_still_work_without_a_trace(tmp_path: Path) -> None:
    """Every existing caller passes no trace and must be unaffected."""
    (tmp_path / "status.txt").write_text("status: ready\n", encoding="utf-8")
    score, _ = score_task(_task(), tmp_path, trace=None)
    assert score.components["status corrected"] == 1.0


# --- the argument -----------------------------------------------------------


def test_a_correct_run_scores_on_both_axes() -> None:
    task = _task()
    result, _, _ = TaskRunner().run(task, "scripted", {"script": task.metadata["scripted_script"]})
    assert result.success is True
    assert result.score.components == {
        "status corrected": 1.0,
        "read before write": 1.0,
        # Resource-level, added after `read before write` turned out to compare
        # the argument's type rather than its value.
        "the file it wrote is the file it read": 1.0,
        "both tools used": 1.0,
        "no failed calls": 1.0,
    }


def test_a_guesser_passes_the_outcome_and_fails_the_trajectory() -> None:
    """The entire argument for this project, in one assertion.

    An agent that writes the right answer without ever reading the file
    produces a perfect workspace. A benchmark inspecting only the end state
    would call that a pass. It is not one.
    """
    task = _task()
    guess = [{"tool": "write_file", "args": {"path": "status.txt", "content": "status: ready\n"}}]
    result, _, _ = TaskRunner().run(task, "scripted", {"script": guess})

    assert result.score.components["status corrected"] == 1.0, "the output really is correct"
    assert result.score.components["read before write"] < 1.0
    assert result.score.components["both tools used"] == 0.0
    assert result.success is False, "outcome-correct, trajectory-wrong, is not a pass"


@pytest.mark.parametrize("name", ["tool_call_match", "tools_used", "no_failed_calls"])
def test_the_trace_scorers_are_registered(name: str) -> None:
    assert name in TRACE_SCORERS


def test_trace_scorers_are_a_separate_registry_from_workspace_scorers() -> None:
    """`docs/plugins.md` counts the workspace registry; these must not inflate it."""
    from tooltrace.core.registry import scorer_registry

    assert not set(TRACE_SCORERS) & set(scorer_registry.names())
