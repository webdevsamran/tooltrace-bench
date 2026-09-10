"""Did it read *this* file before writing it, or just some file?

`tool_call_match` can require a `read_file` before a `write_file`, and that is
what the shipped `read-before-write` task asserted. It compares the argument's
**type**, not its value -- so an agent that reads `notes.txt` and then overwrites
`status.txt` satisfies it completely while doing the exact thing the task exists
to catch.

A blind write is a real correctness signal rather than a style preference: an
agent that overwrites a file it never opened has destroyed whatever was in it and
cannot know whether it needed to.
"""

from __future__ import annotations

from typing import Any

from tooltrace.scoring.trace_scorers import TRACE_SCORERS
from tooltrace.scoring.trace_view import ToolCall, TraceView

resource_order = TRACE_SCORERS["resource_order"]


def trace(*calls: tuple[str, str]) -> TraceView:
    return TraceView(
        calls=tuple(
            ToolCall(seq=index, tool=tool, args={"path": path}, status="ok")
            for index, (tool, path) in enumerate(calls)
        )
    )


def score(view: TraceView, **params: Any) -> tuple[float, str]:
    outcome = resource_order(params, view)
    return outcome.score, outcome.detail


# --- the hole this closes ---------------------------------------------------


def test_reading_one_file_and_writing_another_fails() -> None:
    """The case `tool_call_match` passes completely."""
    value, detail = score(
        trace(("read_file", "notes.txt"), ("write_file", "status.txt")),
        known_resources=["status.txt", "notes.txt"],
    )
    assert value == 0.0
    assert "never read" in detail


def test_reading_then_writing_the_same_file_passes() -> None:
    value, _ = score(
        trace(("read_file", "status.txt"), ("write_file", "status.txt")),
        known_resources=["status.txt"],
    )
    assert value == 1.0


def test_writing_before_reading_fails_even_though_both_happened() -> None:
    """Order matters, and a set-based check would miss this entirely."""
    value, _ = score(
        trace(("write_file", "status.txt"), ("read_file", "status.txt")),
        known_resources=["status.txt"],
    )
    assert value == 0.0


def test_every_write_is_checked_not_just_the_first() -> None:
    value, detail = score(
        trace(
            ("read_file", "a.txt"),
            ("write_file", "a.txt"),
            ("write_file", "b.txt"),
        ),
        known_resources=["a.txt", "b.txt"],
    )
    assert value == 0.0
    assert "b.txt" in detail


# --- creating a file is not a blind write -----------------------------------


def test_creating_a_new_file_is_exempt() -> None:
    """A path that never existed cannot have been read.

    Failing this would fail every task whose answer is a new file, which is most
    of them.
    """
    value, _ = score(
        trace(("write_file", "summary.txt")),
        known_resources=["notes.txt"],
    )
    assert value == 0.0, "with no write to a known resource, nothing was checked"

    value, _ = score(
        trace(("read_file", "notes.txt"), ("write_file", "notes.txt"), ("write_file", "new.txt")),
        known_resources=["notes.txt"],
    )
    assert value == 1.0, "the creation must not fail a trace whose overwrite was fine"


def test_a_task_can_require_a_read_even_of_a_new_file() -> None:
    value, _ = score(
        trace(("write_file", "new.txt")),
        known_resources=["notes.txt"],
        require_read_of_new=True,
    )
    assert value == 0.0


def test_with_no_declared_resources_every_write_is_checked() -> None:
    """Without a starting set there is no way to tell a creation from an
    overwrite, so the stricter reading is taken."""
    value, _ = score(trace(("write_file", "anything.txt")))
    assert value == 0.0


# --- nothing to check is not a pass -----------------------------------------


def test_a_trace_with_no_writes_scores_zero_rather_than_full_marks() -> None:
    """Otherwise an agent that did nothing would satisfy a "read before write"
    assertion perfectly."""
    value, detail = score(trace(("read_file", "status.txt")), known_resources=["status.txt"])
    assert value == 0.0
    assert "nothing was checked" in detail


def test_an_empty_trace_scores_zero() -> None:
    assert score(TraceView())[0] == 0.0


# --- configurability --------------------------------------------------------


def test_the_resource_argument_can_be_named() -> None:
    view = TraceView(
        calls=(
            ToolCall(seq=0, tool="fetch", args={"url": "u"}, status="ok"),
            ToolCall(seq=1, tool="post", args={"url": "u"}, status="ok"),
        )
    )
    value, _ = score(
        view, resource_arg="url", readers=["fetch"], writers=["post"], known_resources=["u"]
    )
    assert value == 1.0


def test_a_call_with_no_resource_argument_is_skipped_rather_than_failing() -> None:
    view = TraceView(
        calls=(
            ToolCall(seq=0, tool="read_file", args={"path": "a.txt"}, status="ok"),
            ToolCall(seq=1, tool="write_file", args={}, status="ok"),
            ToolCall(seq=2, tool="write_file", args={"path": "a.txt"}, status="ok"),
        )
    )
    assert score(view, known_resources=["a.txt"])[0] == 1.0


def test_a_tool_that_is_neither_reader_nor_writer_is_ignored() -> None:
    view = TraceView(
        calls=(
            ToolCall(seq=0, tool="read_file", args={"path": "a.txt"}, status="ok"),
            ToolCall(seq=1, tool="calculator", args={"path": "b.txt"}, status="ok"),
            ToolCall(seq=2, tool="write_file", args={"path": "a.txt"}, status="ok"),
        )
    )
    assert score(view, known_resources=["a.txt", "b.txt"])[0] == 1.0


# --- the shipped task now actually checks what it says ----------------------


def test_the_read_before_write_task_catches_a_blind_write() -> None:
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks.loader import load_all_tasks

    task = next(t for t in load_all_tasks() if t.id == "tool-call-structure/read-before-write")
    reference, _events, _diff = TaskRunner().run(
        task, "scripted", {"script": task.metadata["scripted_script"]}
    )
    assert reference.success, "the reference trajectory must still pass"

    blind, _events, _diff = TaskRunner().run(
        task,
        "scripted",
        {
            "script": [
                {"tool": "write_file", "args": {"path": "status.txt", "content": "status: ready"}}
            ]
        },
    )
    assert not blind.success, (
        "an agent that overwrites the file without reading it must fail the task "
        "whose entire subject is reading before writing"
    )
