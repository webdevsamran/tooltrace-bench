"""Export results as OTel GenAI spans, and score a production trace back.

Two halves of the same bridge.

**Export.** `tooltrace ingest` could always *read* OTel GenAI spans and nothing
could write them, so results ended inside this project: a bundle you could
inspect with these tools and nothing else. Langfuse, Phoenix and Datadog all
speak this format. Being the harness that feeds them is a better position than
competing with them.

**Scoring production traces.** A trace from a real coding agent has no
workspace — the filesystem is gone by the time anyone looks — so every
`(params, workspace)` assertion is unanswerable. The trace-aware scorers are
not, which is what makes scoring a real production run possible at all.

The property that matters most here is honesty about partiality:
`score_trace_only` returns the skipped assertion names, and the CLI reports
`is_partial_score`. A partial score presented as a complete one would be the
worst possible output, because it would understate an agent by exactly the
assertions nobody could evaluate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import main
from tooltrace.exporters.otel import (
    GENAI_CONVENTIONS_VERSION,
    result_to_otel_spans,
    to_otlp_json,
)
from tooltrace.ingest.external import from_otel_spans
from tooltrace.runners.runner import TaskRunner
from tooltrace.scoring.composite import score_trace_only
from tooltrace.scoring.trace_view import TraceView
from tooltrace.tasks import load_all_tasks

_TRACE_TASK = "tool-call-structure/read-before-write"
_PLAIN_TASK = "file-editing/fix-config-typo"


def _task(task_id: str):
    return next(t for t in load_all_tasks() if t.id == task_id)


def _run(task_id: str, script=None):
    task = _task(task_id)
    plan = script if script is not None else task.metadata["scripted_script"]
    return task, *TaskRunner().run(task, "scripted", {"script": plan})


def _spans(task_id: str, script=None) -> list[dict]:
    _, result, events, _ = _run(task_id, script)
    return result_to_otel_spans(result, events)


# --- export -----------------------------------------------------------------


def test_a_run_becomes_an_agent_span_with_tool_children() -> None:
    spans = _spans(_PLAIN_TASK)
    root = spans[0]
    assert root["attributes"]["gen_ai.operation.name"] == "invoke_agent"
    children = spans[1:]
    assert children, "a run with tool calls must produce tool spans"
    for child in children:
        assert child["parentSpanId"] == root["spanId"]
        assert child["attributes"]["gen_ai.operation.name"] == "execute_tool"


def test_every_span_records_which_convention_revision_it_follows() -> None:
    """The GenAI conventions are still experimental; undated data is unreadable."""
    for span in _spans(_PLAIN_TASK):
        assert span["attributes"]["gen_ai.conventions.version"] == GENAI_CONVENTIONS_VERSION


def test_unmeasured_tokens_are_absent_rather_than_zero() -> None:
    """A reported 0 input tokens is a claim; absence is the truth here."""
    root = _spans(_PLAIN_TASK)[0]
    assert "gen_ai.usage.input_tokens" not in root["attributes"]
    assert "gen_ai.usage.output_tokens" not in root["attributes"]


def test_tooltrace_facts_are_namespaced_away_from_the_genai_vocabulary() -> None:
    attributes = _spans(_PLAIN_TASK)[0]["attributes"]
    assert attributes["tooltrace.task.id"] == _PLAIN_TASK
    assert attributes["tooltrace.success"] is True
    for key in attributes:
        assert key.startswith(("gen_ai.", "tooltrace.", "error.")), key


def test_a_failed_tool_call_does_not_emit_a_result_attribute() -> None:
    """`from_otel_spans` derives status from that attribute's presence.

    Emitting it on a failure would make a failed call round-trip as a pass.
    """
    task = _task("failure-recovery/retry-after-tool-failure")
    _, result, events, _ = _run(task.id)
    spans = result_to_otel_spans(result, events)
    failed = [s for s in spans[1:] if s["status"]["code"] == 2]
    assert failed, "this task injects a fault, so a failed span is expected"
    for span in failed:
        assert "gen_ai.tool.call.result" not in span["attributes"]
        assert span["attributes"]["error.type"]


def test_spans_round_trip_through_the_ingest_path() -> None:
    """The exporter and the importer must agree, or neither is trustworthy."""
    spans = _spans(_PLAIN_TASK)
    events = from_otel_spans(spans)
    types = [e.type for e in events]
    assert types.count("tool_request") == len([s for s in spans[1:]])
    assert types.count("tool_request") == types.count("tool_result")


def test_the_otlp_envelope_is_what_a_collector_expects() -> None:
    payload = to_otlp_json(_spans(_PLAIN_TASK))
    scope = payload["resourceSpans"][0]["scopeSpans"][0]
    assert scope["scope"]["name"] == "tooltrace.exporters.otel"
    assert scope["spans"]
    assert json.loads(json.dumps(payload)), "must be plain JSON, no SDK objects"


# --- scoring a production trace ---------------------------------------------


def test_trace_assertions_are_scored_and_workspace_ones_are_named() -> None:
    task = _task(_TRACE_TASK)
    score, _details, skipped = score_trace_only(task, TraceView())
    assert "status corrected" in skipped, "a workspace assertion must be reported as skipped"
    assert set(score.components) == {"read before write", "both tools used", "no failed calls"}


def test_a_task_with_no_trace_assertions_scores_nothing_and_says_so() -> None:
    score, _details, skipped = score_trace_only(_task(_PLAIN_TASK), TraceView())
    assert score.components == {}
    assert skipped, "every assertion needed a workspace; that must be reported"


def test_scoring_discriminates_between_trajectories(tmp_path: Path, capsys) -> None:
    """The bridge is worthless if every production trace scores the same."""
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"spans": _spans(_TRACE_TASK)}), encoding="utf-8")

    guess = [{"tool": "write_file", "args": {"path": "status.txt", "content": "status: ready\n"}}]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"spans": _spans(_TRACE_TASK, guess)}), encoding="utf-8")

    scores = []
    for path in (good, bad):
        assert (
            main(
                [
                    "ingest",
                    "--format",
                    "otel-spans",
                    "--in",
                    str(path),
                    "--score-against",
                    _TRACE_TASK,
                    "--json",
                ]
            )
            == 0
        )
        scores.append(json.loads(capsys.readouterr().out)["score"]["total"])

    assert scores[0] == 1.0
    assert scores[1] < scores[0], "a guessing trajectory must not score like a correct one"


def test_a_partial_score_is_labelled_partial(tmp_path: Path, capsys) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"spans": _spans(_TRACE_TASK)}), encoding="utf-8")
    main(
        [
            "ingest",
            "--format",
            "otel-spans",
            "--in",
            str(path),
            "--score-against",
            _TRACE_TASK,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["is_partial_score"] is True
    assert payload["skipped_assertions"] == ["status corrected"]
    assert "need a workspace" in captured.err


def test_an_unknown_task_is_refused(tmp_path: Path, capsys) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"spans": _spans(_PLAIN_TASK)}), encoding="utf-8")
    code = main(
        ["ingest", "--format", "otel-spans", "--in", str(path), "--score-against", "no/such-task"]
    )
    assert code != 0
    assert "unknown task" in capsys.readouterr().err


def test_ingest_without_scoring_is_unchanged(tmp_path: Path, capsys) -> None:
    """Every existing caller passes no `--score-against` and must be unaffected."""
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"spans": _spans(_PLAIN_TASK)}), encoding="utf-8")
    assert main(["ingest", "--format", "otel-spans", "--in", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "score" not in payload
    assert payload["events"] > 0


@pytest.mark.parametrize("task_id", [_PLAIN_TASK, _TRACE_TASK])
def test_export_never_transmits_anything(task_id: str) -> None:
    """Producing spans must not send them; that is the caller's decision."""
    import tooltrace.exporters.otel as exporter

    source = Path(exporter.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "urlopen", "socket"):
        assert forbidden not in source, f"the exporter must not import {forbidden}"
    assert result_to_otel_spans(*_run(task_id)[1:3])
