"""Five functions that existed with no caller outside the test suite.

This repository has a recurring defect shape, and it is not broken code — it is
*correct* code nothing reaches. A wheel whose schemas were never packaged. A
metrics package with no callers. A Trace Explorer fetching filenames nobody
publishes. An anti-gaming check inspecting nothing.

A scan for functions referenced only by `tests/` found five more, and in four of
them the absent caller was itself the defect:

- **`load_all_registries`** exists to import all four registries. `doctor`
  imported three by hand and omitted `sandbox`, so a command described as a
  registry health check never reported the sandbox providers at all.
- **`verify_bundle_signature`** was reachable from Python only, so the
  distinction the docs draw — checksums are tamper-*evident*, a signature says
  *who* — could not be exercised by a user.
- **`environment_note`** states that `api_error` faults never touch the network.
  Nothing showed it to anyone, so a reader of "injected api_error" could
  reasonably have believed a network fault was simulated.
- **`probe_command`** (added in the same change as `init`, and immediately
  orphaned) checks whether the configured command exists. Without it, "not on
  PATH" and "the agent failed the task" produce the same score.
- **`calls_to` / `succeeded_calls`** on `TraceView` were convenience readers with
  no callers, while a scorer re-implemented one of them inline.

Each test below fails on the state before the fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import main
from tooltrace.core.models import TraceEvent
from tooltrace.scoring.trace_scorers import TRACE_SCORERS
from tooltrace.scoring.trace_view import TraceView

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"


# --- doctor reports every registry ------------------------------------------


def test_doctor_reports_the_sandbox_providers(capsys) -> None:
    """It reported tools, agents and scorers, and silently skipped sandboxes."""
    assert main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "sandboxes" in payload, "a registry health check that omits a registry"
    assert payload["sandboxes"], "sandbox_registry was never populated"


def test_doctor_reports_all_four_registries(capsys) -> None:
    main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    for registry in ("tools", "agents", "scorers", "sandboxes"):
        assert payload[registry], f"{registry} registry is empty in doctor's report"


def test_load_all_registries_populates_every_one() -> None:
    from tooltrace.core.registry import (
        agent_registry,
        load_all_registries,
        sandbox_registry,
        scorer_registry,
        tool_registry,
    )

    load_all_registries()
    for registry in (tool_registry, agent_registry, scorer_registry, sandbox_registry):
        assert registry.names(), f"{registry} is empty after load_all_registries()"


# --- signature verification is reachable ------------------------------------


def _bundle() -> Path:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    return bundles[0]


def test_verify_does_not_check_a_signature_unless_asked(capsys) -> None:
    assert main(["verify", str(_bundle()), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["signature"] == {"checked": False}
    assert payload["ok"] is True, "not asking about a signature is not a failure"


def test_verify_can_be_asked_about_a_signature(tmp_path: Path, capsys) -> None:
    """Reachable from the CLI at all -- it was Python-only before."""
    signature = tmp_path / "bundle.sig"
    signature.write_text("not a real signature", encoding="utf-8")
    code = main(["verify", str(_bundle()), "--signature", str(signature), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["signature"]["checked"] is True
    # Either cosign is absent (reason given) or it rejects the file. Both are
    # honest outcomes; silently passing is not.
    assert payload["signature"]["verified"] is False
    assert code != 0, "an unverifiable signature the caller asked about must fail"


def test_an_unverifiable_signature_does_not_mask_the_checksums(tmp_path: Path, capsys) -> None:
    """The two checks answer different questions and are reported separately."""
    signature = tmp_path / "bundle.sig"
    signature.write_text("nope", encoding="utf-8")
    main(["verify", str(_bundle()), "--signature", str(signature), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["checksums_ok"] is True
    assert payload["ok"] is False


# --- the perturbation note travels with the result --------------------------


def test_perturb_states_that_api_faults_never_touch_the_network(capsys) -> None:
    """Without this, "injected api_error" reads as a simulated network fault."""
    code = main(
        [
            "perturb",
            "--task",
            "failure-recovery/retry-after-tool-failure",
            "--agent",
            "scripted",
            "--runs",
            "1",
            "--json",
        ]
    )
    assert code in {0, 5}
    payload = json.loads(capsys.readouterr().out)
    assert "environment_note" in payload
    assert "no real network traffic" in payload["environment_note"]


# --- init checks the command before running it ------------------------------


def test_init_says_when_the_command_is_not_on_path(tmp_path: Path) -> None:
    from tooltrace.cli.init import run_init

    _, payload = run_init(
        tmp_path,
        adapter="subprocess",
        command="definitely-not-a-real-binary-xyz {objective}",
        write_workflow=False,
        do_verify=False,
    )
    assert any("will not start" in note for note in payload["plan"]["notes"])


def test_a_command_that_never_started_is_not_reported_as_a_measurement(tmp_path: Path) -> None:
    """The failure that matters: "not on PATH" and "the agent failed" score alike.

    Telling someone a missing binary is "a real measurement, not a setup problem"
    sends them to debug an agent that never ran.
    """
    from tooltrace.cli.init import run_init

    _, payload = run_init(
        tmp_path,
        adapter="subprocess",
        command="definitely-not-a-real-binary-xyz {objective}",
        write_workflow=False,
    )
    assert "measures the config, not the agent" in payload["report"]
    assert "not a setup problem" not in payload["report"]


def test_a_real_command_is_not_flagged(tmp_path: Path) -> None:
    import sys

    from tooltrace.cli.init import run_init

    _, payload = run_init(
        tmp_path,
        adapter="subprocess",
        command=f"{Path(sys.executable).name} -c pass",
        write_workflow=False,
        do_verify=False,
    )
    assert not any("will not start" in note for note in payload["plan"]["notes"])


# --- the trace view's readers have callers ----------------------------------


def _trace(*calls: tuple[int, str, str]) -> TraceView:
    stamp = "2026-09-09T00:00:00+00:00"
    events = []
    for seq, tool, status in calls:
        events.append(
            TraceEvent(
                seq=seq, timestamp=stamp, type="tool_request", payload={"tool": tool, "args": {}}
            )
        )
        events.append(
            TraceEvent(
                seq=seq + 100,
                timestamp=stamp,
                type="tool_result",
                payload={"tool": tool, "status": status},
            )
        )
    return TraceView.from_events(events)


def test_a_count_scorer_exists_at_all() -> None:
    """`tools_used` cannot tell one call from twenty, and twenty identical calls
    is the signature of an agent stuck in a loop."""
    assert "tool_call_count" in TRACE_SCORERS


def test_it_enforces_a_minimum() -> None:
    trace = _trace((1, "read_file", "ok"))
    scorer = TRACE_SCORERS["tool_call_count"]
    assert scorer({"tool": "read_file", "min": 1}, trace).score == 1.0
    assert scorer({"tool": "read_file", "min": 2}, trace).score == 0.0


def test_it_enforces_a_maximum_so_thrashing_fails() -> None:
    trace = _trace(
        (1, "patch_file", "error"), (2, "patch_file", "error"), (3, "patch_file", "error")
    )
    scorer = TRACE_SCORERS["tool_call_count"]
    assert scorer({"tool": "patch_file", "max": 2}, trace).score == 0.0
    assert scorer({"tool": "patch_file", "max": 5}, trace).score == 1.0


def test_it_can_count_only_the_calls_that_worked() -> None:
    trace = _trace((1, "patch_file", "error"), (2, "patch_file", "ok"))
    scorer = TRACE_SCORERS["tool_call_count"]
    assert scorer({"tool": "patch_file", "min": 2}, trace).score == 1.0
    assert scorer({"tool": "patch_file", "min": 2, "successful_only": True}, trace).score == 0.0


def test_an_unnamed_tool_scores_zero_rather_than_matching_everything() -> None:
    scorer = TRACE_SCORERS["tool_call_count"]
    assert scorer({}, _trace((1, "read_file", "ok"))).score == 0.0


def test_the_readers_agree_with_the_view() -> None:
    trace = _trace((1, "read_file", "ok"), (2, "read_file", "error"), (3, "shell", "ok"))
    assert len(trace.calls_to("read_file")) == 2
    assert len(trace.calls_to("shell")) == 1
    assert {c.tool for c in trace.succeeded_calls()} == {"read_file", "shell"}
    assert len(trace.succeeded_calls()) == 2


def test_no_failed_calls_agrees_with_succeeded_calls() -> None:
    """Two definitions of "a call that succeeded" would drift silently."""
    trace = _trace((1, "read_file", "ok"), (2, "read_file", "error"))
    outcome = TRACE_SCORERS["no_failed_calls"]({"allow": 0}, trace)
    assert outcome.score == 0.0
    assert len(trace.calls) - len(trace.succeeded_calls()) == 1
