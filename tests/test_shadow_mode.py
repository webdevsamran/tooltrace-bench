"""Shadow mode, and the outcome comparison it refuses to make.

Shadow mode usually means running a candidate against live traffic and
comparing outcomes. **That is not possible here.** A production trace happened
against real systems holding real state at a particular moment; re-running a
candidate in a temp workspace is a different task that happens to share an
objective, and any outcome it produces is an outcome in a sandbox rather than a
prediction about production.

So this compares decisions -- which is what a replayed trace can actually
support -- and says so at the same prominence as the numbers. A report that
looked like an outcome comparison would be the most dangerous thing in this
module, because it would be read as "the candidate would have been fine".

The alignment is checked against `tests/fixtures/trace_alignment.json`, which
the dashboard's TypeScript implementation reads too. Two implementations that
drifted would give two different answers about where the same pair of runs
diverged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tooltrace.analysis.shadow import (
    BOTH,
    CANDIDATE_ONLY,
    RECORDED_ONLY,
    Step,
    align,
    render_markdown,
    shadow_report,
    steps_from_events,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "trace_alignment.json").read_text("utf-8")
)

#: The fixture's vocabulary, which is the dashboard's. Mapped rather than
#: renamed on either side: "left/right" is the right word for two runs side by
#: side and "recorded/candidate" is the right word here.
SIDES = {BOTH: "both", RECORDED_ONLY: "left", CANDIDATE_ONLY: "right"}


def event(tool: str, resource: str = "", seq: int = 0) -> dict[str, Any]:
    return {
        "seq": seq,
        "type": "tool_request",
        "payload": {"tool": tool, "args": {"path": resource}},
    }


# --- the shared contract ----------------------------------------------------


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_the_alignment_matches_the_shared_fixture(case: dict) -> None:
    """The dashboard's TypeScript implementation reads the same cases."""
    left = [Step(tool, resource) for tool, resource in case["left"]]
    right = [Step(tool, resource) for tool, resource in case["right"]]
    rows = align(left, right)
    assert [SIDES[row["side"]] for row in rows] == case["sides"]


def test_the_fixture_covers_enough_to_be_a_contract() -> None:
    assert len(FIXTURE["cases"]) >= 8


def test_the_fixture_explains_why_it_exists() -> None:
    """A shared fixture nobody understands gets edited to make a test pass."""
    assert any("drift" in line for line in FIXTURE["why"])


# --- reading a trace --------------------------------------------------------


def test_only_tool_requests_count_as_decisions() -> None:
    events = [
        {"seq": 0, "type": "run_started", "payload": {}},
        event("read_file", "a.txt", 1),
        {"seq": 2, "type": "tool_result", "payload": {"tool": "read_file", "status": "ok"}},
    ]
    assert [s.tool for s in steps_from_events(events)] == ["read_file"]


def test_the_resource_is_taken_from_whichever_argument_names_one() -> None:
    events = [{"seq": 0, "type": "tool_request", "payload": {"tool": "http", "args": {"url": "u"}}}]
    assert steps_from_events(events)[0].resource == "u"


def test_a_call_with_no_recognisable_resource_still_counts_as_a_decision() -> None:
    """Dropping it would silently shorten one side and shift the alignment."""
    events = [{"seq": 0, "type": "tool_request", "payload": {"tool": "calculator", "args": {}}}]
    assert len(steps_from_events(events)) == 1


def test_a_call_with_no_tool_name_is_skipped() -> None:
    events = [{"seq": 0, "type": "tool_request", "payload": {"args": {"path": "a"}}}]
    assert steps_from_events(events) == []


# --- the report -------------------------------------------------------------


def test_it_names_the_step_where_the_candidate_stopped_agreeing() -> None:
    recorded = [event("read_file", "a.txt", 0), event("patch_file", "a.txt", 1)]
    candidate = [event("read_file", "a.txt", 0), event("write_file", "a.txt", 1)]
    report = shadow_report(recorded, candidate)
    assert report["shared_steps"] == 1
    assert report["diverged_at"] == 1
    assert "diverged at step 2" in report["statement"]


def test_an_identical_candidate_never_diverges() -> None:
    trace = [event("read_file", "a.txt", 0)]
    report = shadow_report(trace, trace)
    assert report["diverged_at"] is None
    assert "never diverged" in report["statement"]


def test_steps_unique_to_each_side_are_listed_separately() -> None:
    recorded = [event("read_file", "a.txt", 0)]
    candidate = [event("read_file", "a.txt", 0), event("shell", "ls", 1)]
    report = shadow_report(recorded, candidate)
    assert report["only_in_recorded"] == []
    assert report["only_in_candidate"] == [{"tool": "shell", "resource": "ls"}]


def test_an_empty_candidate_is_a_total_divergence_not_an_error() -> None:
    report = shadow_report([event("read_file", "a.txt")], [])
    assert report["candidate_steps"] == 0
    assert report["diverged_at"] == 0


# --- the two refusals -------------------------------------------------------


def test_the_report_says_outcomes_are_not_compared() -> None:
    """The most dangerous thing this module could imply is "the candidate would
    have been fine"."""
    report = shadow_report([event("read_file", "a")], [event("read_file", "a")])
    assert "decisions, not outcomes" in report["outcomes_not_compared"]
    assert "different task sharing an objective" in report["outcomes_not_compared"]


def test_the_report_says_a_divergence_is_not_a_defect() -> None:
    """The candidate may be doing something better, and the recorded run is a
    log rather than an oracle -- production is where the mistakes happened."""
    report = shadow_report([event("read_file", "a")], [event("shell", "ls")])
    assert "not a fault" in report["divergence_is_not_a_defect"]
    assert "rather than an oracle" in report["divergence_is_not_a_defect"]


def test_both_caveats_survive_into_the_rendered_table() -> None:
    """A caveat that only exists in the JSON is a caveat nobody reads."""
    rendered = render_markdown(shadow_report([event("read_file", "a")], [event("shell", "ls")]))
    assert "decisions, not outcomes" in rendered
    assert "not a fault" in rendered


# --- the CLI ----------------------------------------------------------------


def write_trace(path: Path, events: list[dict[str, Any]]) -> Path:
    """A JSONL trace the real `TraceEvent` model will accept.

    The field is `timestamp`. Writing a fixture the loader rejects would test
    the loader's error path and nothing else.
    """
    path.write_text(
        chr(10).join(json.dumps({**e, "timestamp": "2026-09-10T00:00:00Z"}) for e in events),
        encoding="utf-8",
    )
    return path


def test_the_cli_compares_two_recorded_traces(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    recorded = write_trace(tmp_path / "recorded.jsonl", [event("read_file", "a.txt", 0)])
    candidate = write_trace(tmp_path / "candidate.jsonl", [event("shell", "ls", 0)])
    assert (
        main(["shadow", "--recorded", str(recorded), "--candidate", str(candidate), "--json"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["diverged_at"] == 0


def test_the_cli_runs_the_candidate_when_no_second_trace_is_given(tmp_path: Path, capsys) -> None:
    """Asking the caller to produce one by hand is the step at which most people
    stop."""
    from tooltrace.cli.main import main

    recorded = write_trace(tmp_path / "recorded.jsonl", [event("read_file", "config.ini", 0)])
    code = main(
        [
            "shadow",
            "--recorded",
            str(recorded),
            "--task",
            "file-editing/fix-config-typo",
            "--agent",
            "scripted",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_steps"] > 0


def test_the_cli_refuses_an_empty_recorded_trace(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert main(["shadow", "--recorded", str(empty)]) != 0
    assert "empty" in capsys.readouterr().err
