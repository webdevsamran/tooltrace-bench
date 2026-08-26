"""External trace ingestion: OTel GenAI spans and OpenAI step logs."""

from __future__ import annotations

import json

from tooltrace.analysis.failures import classify
from tooltrace.core.models import TraceEvent
from tooltrace.ingest import format_counts, from_openai_steps, from_otel_spans

OTEL_SPANS = [
    {
        "name": "chat gpt-x",
        "attributes": {"gen_ai.system": "langgraph-agent", "gen_ai.request.model": "gpt-x"},
    },
    {
        "name": "execute_tool read_file",
        "attributes": {
            "gen_ai.tool.name": "read_file",
            "gen_ai.tool.call.arguments": json.dumps({"path": "notes.txt"}),
            "gen_ai.tool.call.result": "value=FOO",
        },
    },
    {"name": "unrelated-span", "attributes": {}},
]

OPENAI_STEPS = [
    {"content": "I will read the file first.", "tool_calls": []},
    {
        "content": None,
        "tool_calls": [
            {
                "function": {
                    "name": "patch_file",
                    "arguments": '{"path": "notes.txt", "patch": "-FOO+BAR"}',
                }
            }
        ],
        "tool_results": [{"tool": "patch_file"}],
    },
]


def _seqs(events: list[TraceEvent]) -> list[int]:
    return [e.seq for e in events]


def test_otel_spans_convert_to_tool_pairs() -> None:
    events = from_otel_spans(OTEL_SPANS)
    types = [e.type for e in events]
    assert types[0] == "task_start"
    assert types[-1] == "task_end"
    # request/result pair for the tool span
    req = next(e for e in events if e.type == "tool_request")
    res = next(e for e in events if e.type == "tool_result")
    assert req.payload["tool"] == "read_file"
    assert req.payload["args"] == {"path": "notes.txt"}
    assert res.payload["status"] == "ok"
    assert res.seq == req.seq + 1
    # agent detected from gen_ai.system
    assert events[-1].payload["agent"] == "langgraph-agent"


def test_otel_tool_span_without_result_is_error() -> None:
    spans = [{"name": "t", "attributes": {"gen_ai.tool.name": "shell"}}]
    events = from_otel_spans(spans)
    res = next(e for e in events if e.type == "tool_result")
    assert res.payload["status"] == "error"


def test_openai_steps_decode_json_arguments() -> None:
    events = from_openai_steps(OPENAI_STEPS)
    reqs = [e for e in events if e.type == "tool_request"]
    assert len(reqs) == 1
    assert reqs[0].payload["args"] == {"path": "notes.txt", "patch": "-FOO+BAR"}
    msgs = [e for e in events if e.type == "agent_message"]
    assert msgs[0].payload["text"] == "I will read the file first."
    results = [e for e in events if e.type == "tool_result"]
    assert results[0].payload["status"] == "ok"


def test_ingested_events_have_monotonic_seq_and_valid_types() -> None:
    for events in (from_otel_spans(OTEL_SPANS), from_openai_steps(OPENAI_STEPS)):
        seqs = _seqs(events)
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        allowed = {
            "task_start",
            "agent_message",
            "tool_request",
            "tool_result",
            "workspace_diff",
            "validation",
            "retry_recovery",
            "task_end",
        }
        assert {e.type for e in events} <= allowed


def test_ingested_trace_classifies_with_standard_taxonomy() -> None:
    events = from_otel_spans([{"name": "s", "attributes": {}}])
    assert classify(events) == classify([])  # both clean → same non-failure reason


def test_format_counts() -> None:
    counts = format_counts(from_openai_steps(OPENAI_STEPS))
    assert counts["task_start"] == 1 and counts["task_end"] == 1


def test_cli_ingest_writes_jsonl(tmp_path) -> None:
    from tooltrace.cli.main import main as cli_main

    src = tmp_path / "spans.json"
    out = tmp_path / "out.trace.jsonl"
    src.write_text(json.dumps({"spans": OTEL_SPANS}), encoding="utf-8")
    code = cli_main(
        [
            "ingest",
            "--format",
            "otel-spans",
            "--in",
            str(src),
            "--out",
            str(out),
            "--task-id",
            "ingested/demo",
            "--agent",
            "otel-agent",
            "--json",
        ]
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["type"] == "task_start"
    assert parsed[-1]["payload"]["agent"] == "otel-agent"


def test_cli_ingest_usage_error_on_bad_input(tmp_path) -> None:
    from tooltrace.cli.main import main as cli_main

    src = tmp_path / "bad.json"
    src.write_text('{"unexpected": true}', encoding="utf-8")
    assert cli_main(["ingest", "--format", "openai-steps", "--in", str(src)]) != 0
    missing = tmp_path / "nope.json"
    assert cli_main(["ingest", "--format", "openai-steps", "--in", str(missing)]) != 0
