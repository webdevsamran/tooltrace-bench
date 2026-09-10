"""Did the agent undo its own work?

Every workspace scorer sees the **final** state. That cannot distinguish an
agent that went straight to the answer from one that wrote it, overwrote it with
something else, and wrote it back -- identical end state, very different agents.
On a long-horizon task the second one is a session that will not survive one
more turn, and nothing else in this project notices.

`state_drift` reads the trace instead: for each resource, the sequence of
writes, and whether a later one dropped content an earlier one added.

It is deliberately the *trace-visible* half. It cannot see a change made by
something other than a tool call, and it cannot see whether the content that
survived is correct -- that is what the workspace assertions are for, and
claiming otherwise would make it a second, worse copy of them.
"""

from __future__ import annotations

from typing import Any

from tooltrace.scoring.trace_scorers import TRACE_SCORERS
from tooltrace.scoring.trace_view import ToolCall, TraceView

state_drift = TRACE_SCORERS["state_drift"]


def writes(*calls: tuple[str, str]) -> TraceView:
    return TraceView(
        calls=tuple(
            ToolCall(
                seq=index,
                tool="write_file",
                args={"path": path, "content": content},
                status="ok",
            )
            for index, (path, content) in enumerate(calls)
        )
    )


def score(view: TraceView, **params: Any) -> tuple[float, str]:
    outcome = state_drift(params, view)
    return outcome.score, outcome.detail


# --- the failure it exists to catch -----------------------------------------


def test_dropping_a_line_it_wrote_earlier_is_a_finding() -> None:
    value, detail = score(writes(("a.txt", "one\ntwo\n"), ("a.txt", "one\n")))
    assert value == 0.0
    assert "two" in detail


def test_writing_it_back_afterwards_does_not_erase_the_finding() -> None:
    """Identical end state, and the middle step is the whole point.

    An agent that thrashes and recovers has a problem the final state hides.
    """
    value, _ = score(writes(("a.txt", "one\ntwo\n"), ("a.txt", "one\n"), ("a.txt", "one\ntwo\n")))
    assert value == 0.0


def test_adding_to_what_it_wrote_is_not_drift() -> None:
    value, _ = score(writes(("a.txt", "one\n"), ("a.txt", "one\ntwo\n")))
    assert value == 1.0


def test_rewriting_a_line_is_drift_only_if_the_old_one_is_gone() -> None:
    value, _ = score(writes(("a.txt", "status: draft\n"), ("a.txt", "status: final\n")))
    assert value == 0.0, "the draft line was written by the agent and then removed by it"


def test_each_resource_is_tracked_separately() -> None:
    """Writing b.txt does not undo a.txt."""
    value, _ = score(writes(("a.txt", "one\n"), ("b.txt", "other\n"), ("a.txt", "one\ntwo\n")))
    assert value == 1.0


# --- what it deliberately does not flag -------------------------------------


def test_the_first_write_to_a_file_can_never_be_drift() -> None:
    """It replaced content the *task* provided, not content the agent wrote.

    Flagging that would fail every task whose answer is an edit.
    """
    value, detail = score(writes(("a.txt", "replaced\n")))
    assert value == 1.0
    assert "nothing was rewritten" in detail


def test_a_single_write_reports_why_rather_than_just_passing() -> None:
    """ "Nothing was overwritten" and "the agent never rewrote a file" are
    different, and only the second is a property of this run."""
    _value, detail = score(writes(("a.txt", "x\n")))
    assert "nothing was rewritten, so nothing was undone" in detail


def test_whitespace_only_changes_are_not_drift() -> None:
    value, _ = score(writes(("a.txt", "one\n  two\n"), ("a.txt", "one\ntwo\n")))
    assert value == 1.0


def test_reordering_lines_is_not_drift() -> None:
    """Nothing was lost, and a line-order check would be a style opinion."""
    value, _ = score(writes(("a.txt", "one\ntwo\n"), ("a.txt", "two\none\n")))
    assert value == 1.0


def test_a_call_with_no_content_argument_is_skipped() -> None:
    view = TraceView(
        calls=(
            ToolCall(seq=0, tool="write_file", args={"path": "a.txt"}, status="ok"),
            ToolCall(seq=1, tool="write_file", args={"path": "a.txt", "content": "x"}, status="ok"),
        )
    )
    assert score(view)[0] == 1.0


def test_a_tool_that_is_not_a_writer_is_ignored() -> None:
    view = TraceView(
        calls=(
            ToolCall(
                seq=0, tool="write_file", args={"path": "a", "content": "one\ntwo"}, status="ok"
            ),
            ToolCall(seq=1, tool="read_file", args={"path": "a", "content": ""}, status="ok"),
        )
    )
    assert score(view)[0] == 1.0


# --- narrowing it to what a task cares about --------------------------------


def test_markers_narrow_the_check_to_declared_content() -> None:
    """Without them, rewriting boilerplate reads as drift on a task that never
    asked for the boilerplate."""
    view = writes(("a.txt", "keepme\nboilerplate\n"), ("a.txt", "keepme\n"))
    assert score(view)[0] == 0.0
    assert score(view, markers=["keepme"])[0] == 1.0


def test_a_marker_that_disappears_is_still_caught() -> None:
    view = writes(("a.txt", "keepme\n"), ("a.txt", "gone\n"))
    assert score(view, markers=["keepme"])[0] == 0.0


def test_the_writer_set_can_be_declared() -> None:
    view = TraceView(
        calls=(
            ToolCall(seq=0, tool="publish", args={"path": "a", "content": "one\ntwo"}, status="ok"),
            ToolCall(seq=1, tool="publish", args={"path": "a", "content": "one"}, status="ok"),
        )
    )
    assert score(view)[0] == 1.0, "an unknown tool is not a writer by default"
    assert score(view, writers=["publish"])[0] == 0.0


# --- on the real long-horizon task ------------------------------------------


def test_the_long_horizon_reference_trajectory_still_passes() -> None:
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks.loader import load_all_tasks

    task = next(t for t in load_all_tasks() if t.id == "long-horizon/resume-from-session-state")
    result, _events, _diff = TaskRunner().run(
        task, "scripted", {"script": task.metadata["scripted_script"]}
    )
    assert result.success


def test_an_agent_that_thrashes_fails_a_task_every_other_assertion_passes() -> None:
    """The end state is correct and the session is not one you would trust."""
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks.loader import load_all_tasks

    task = next(t for t in load_all_tasks() if t.id == "long-horizon/resume-from-session-state")
    thrashing = [
        {"tool": "read_file", "args": {"path": "session.json"}},
        {
            "tool": "write_file",
            "args": {"path": "done.txt", "content": "alpha\nbeta\ngamma\ndelta\n"},
        },
        {"tool": "write_file", "args": {"path": "done.txt", "content": "alpha\nbeta\ngamma\n"}},
        {
            "tool": "write_file",
            "args": {"path": "done.txt", "content": "alpha\nbeta\ngamma\ndelta\n"},
        },
        {
            "tool": "write_file",
            "args": {"path": "session.json", "content": '{"session": 3, "cursor": 4}'},
        },
    ]
    result, _events, _diff = TaskRunner().run(task, "scripted", {"script": thrashing})
    assert result.score.components["it never undid its own work"] == 0.0
    assert not result.success
