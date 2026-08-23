"""Tests for contamination assessment (f4), provider protocol layers (f49),
and checkpoint-based partial replay (f80)."""

from __future__ import annotations

from tests.conftest import make_task
from tooltrace.agents.interop import (
    ANTHROPIC_COMPAT_SPEC,
    GEMINI_COMPAT_SPEC,
    OPENAI_COMPAT_SPEC,
    build_provider_request,
    parse_provider_tool_call,
)
from tooltrace.core.models import TraceEvent
from tooltrace.replay import replay_from_checkpoint
from tooltrace.tasks.governance import assess_contamination

# --- feature 4: contamination-aware metadata -------------------------------


def test_contamination_clean_when_no_signals():
    flag = assess_contamination("t/x", objective_text="rotate log rotation policy")
    assert flag.level == "none"
    assert flag.verification_state == "declared"


def test_contamination_high_with_leak_reports():
    flag = assess_contamination(
        "t/y", objective_text="solve two sum", known_leak_reports=["https://example.com/leak"]
    )
    assert flag.level == "high"
    assert flag.public_sources == ["https://example.com/leak"]


def test_contamination_medium_from_public_repo_and_generic_files():
    flag = assess_contamination(
        "t/z",
        objective_text="fix the bug",
        fixture_names=["main.py"],
        derived_from_public_repo=True,
    )
    assert flag.level in {"medium", "high"}
    assert "public repository" in flag.reason


# --- feature 49: provider-compatible protocol layers -----------------------


def test_openai_request_shape():
    req = build_provider_request(
        OPENAI_COMPAT_SPEC,
        model="m1",
        system="s",
        user="u",
        tools=[{"name": "read_file", "description": "d", "parameters": {}}],
        api_key_ref="MY_KEY_ENV",
    )
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer MY_KEY_ENV"
    assert req["body"]["tools"][0]["type"] == "function"


def test_anthropic_request_and_parse():
    req = build_provider_request(
        ANTHROPIC_COMPAT_SPEC, model="m2", system="s", user="u", api_key_ref="K"
    )
    assert req["path"] == "/v1/messages"
    assert req["headers"]["anthropic-version"] == "2023-06-01"
    resp = {"content": [{"type": "tool_use", "name": "patch_file", "input": {"path": "a"}}]}
    call = parse_provider_tool_call(ANTHROPIC_COMPAT_SPEC, resp)
    assert call == {"name": "patch_file", "arguments": {"path": "a"}}


def test_gemini_request_and_parse():
    req = build_provider_request(
        GEMINI_COMPAT_SPEC, model="gemini-x", system="s", user="u", api_key_ref="K"
    )
    assert req["path"] == "/v1beta/models/gemini-x:generateContent"
    assert req["headers"]["x-goog-api-key"] == "K"
    resp = {
        "candidates": [
            {"content": {"parts": [{"functionCall": {"name": "run_cmd", "args": {"cmd": "ls"}}}]}}
        ]
    }
    call = parse_provider_tool_call(GEMINI_COMPAT_SPEC, resp)
    assert call == {"name": "run_cmd", "arguments": {"cmd": "ls"}}


def test_parse_malformed_response_returns_none():
    assert parse_provider_tool_call(OPENAI_COMPAT_SPEC, {"unexpected": True}) is None


# --- feature 80: partial replay from checkpoint ----------------------------


def _events():
    ts = "2026-08-23T00:00:00+00:00"
    return [
        TraceEvent(
            seq=0,
            timestamp=ts,
            type="tool_request",
            payload={"tool": "write_file", "args": {"path": "a.txt", "content": "x"}},
        ),
        TraceEvent(
            seq=1, timestamp=ts, type="tool_result", payload={"tool": "write_file", "status": "ok"}
        ),
        TraceEvent(
            seq=2,
            timestamp=ts,
            type="tool_request",
            payload={"tool": "read_file", "args": {"path": "a.txt"}},
        ),
        TraceEvent(
            seq=3, timestamp=ts, type="tool_result", payload={"tool": "read_file", "status": "ok"}
        ),
    ]


def _task(tmp_path):
    return make_task(
        id="replay/partial",
        starting_workspace={"a.txt": "x"},
        allowed_tools=["write_file", "read_file"],
    )


def test_partial_replay_skips_prefix_and_notes_it(tmp_path):
    task = _task(tmp_path)
    report = replay_from_checkpoint(task, _events(), checkpoint_seq=2)
    assert any(e.startswith("partial-replay:") for e in report.errors)
    # only the suffix pair was re-executed
    assert report.total_requests == 1


def test_partial_replay_from_zero_equals_full(tmp_path):
    task = _task(tmp_path)
    full = replay_from_checkpoint(task, _events(), checkpoint_seq=0)
    assert full.total_requests == 2
