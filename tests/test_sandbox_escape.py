"""The sandbox boundary must hold against attempts, not just against a helper.

`scripts/sandbox_check.py` calls `resolve_in_workspace` with bad paths and
verifies defaults. That is a conformance check on a function; it proves the
helper rejects what it is handed. An agent never calls that helper. It calls
tools, through `ToolExecutor`, and that is the path an escape would actually
take — so that is the path this suite attacks.

Two properties matter as much as the attempts themselves:

- Success is judged on **evidence**, not on the tool's report. A write that
  claims to have failed but left a file outside the workspace still escaped.
- The documented limits of the local sandbox are **attempted and reported**, not
  skipped. `shell` can write outside the workspace and read the environment;
  `docs/threat-model.md` says so, and a suite that quietly omits the attacks it
  would fail is a suite that measures nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from tooltrace.sandbox.escape import (
    CANARY,
    Attempt,
    build_attempts,
    check_isolation,
    run_attempts,
)

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return check_isolation()


# --- the boundary holds -----------------------------------------------------


def test_no_must_block_attempt_escapes(report: dict[str, Any]) -> None:
    assert report["ok"], f"sandbox boundary broken: {report['breaches']}"
    assert report["breaches"] == []


def test_the_suite_actually_tries_a_meaningful_number_of_attacks(report: dict[str, Any]) -> None:
    """A suite of two attempts would pass just as easily and prove much less."""
    assert report["attempts"] >= 14


@pytest.mark.parametrize(
    "name",
    [
        "write above the workspace with ..",
        "write to an absolute path",
        "read an absolute system path",
        "http egress while the policy is disabled",
        "git push",
    ],
)
def test_each_named_escape_is_blocked(report: dict[str, Any], name: str) -> None:
    result = next(r for r in report["results"] if r["name"] == name)
    assert result["escaped"] is False, result["detail"]


def test_every_filesystem_tool_is_attacked() -> None:
    """A boundary is only as good as its least-guarded door."""
    attacked = {a.tool for a in build_attempts(Path("/tmp/x"))}
    for tool in ("read_file", "write_file", "patch_file", "list_directory", "search_text"):
        assert tool in attacked, f"{tool} is never attacked"


# --- honesty about what is not blocked --------------------------------------


def test_the_documented_limits_are_attempted_not_skipped(report: dict[str, Any]) -> None:
    attempted = {r["name"] for r in report["results"] if r["severity"] == "known_limit"}
    assert "shell writes above the workspace" in attempted
    assert "shell reads the environment" in attempted


def test_the_threat_model_still_describes_the_local_sandbox_honestly(
    report: dict[str, Any],
) -> None:
    """If shell egress is now blocked, the docs understate the sandbox."""
    threat_model = (_ROOT / "docs" / "threat-model.md").read_text(encoding="utf-8")
    if report["known_limits_confirmed"]:
        assert "shell" in threat_model.lower(), (
            "the suite confirmed a shell-based escape; the threat model must say so"
        )


# --- non-vacuousness --------------------------------------------------------


def test_an_escape_is_detected_by_evidence_on_disk(tmp_path: Path) -> None:
    """The load-bearing property: a write that lands outside is caught.

    Without this, the suite would only be as trustworthy as the tool's own
    report of whether it succeeded.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside" / f"{CANARY}.txt"

    # A shell command that genuinely writes outside; on the local sandbox this
    # is the documented gap, so it must be reported as an escape.
    results = run_attempts(
        workspace,
        outside,
        [
            Attempt(
                "deliberate breakout",
                "shell",
                {"command": f'echo {CANARY} > "{outside.as_posix()}"'},
                severity="must_block",
                escaped_if_exists=outside.as_posix(),
            )
        ],
    )
    assert results[0].escaped is True, (
        "a file written outside the workspace was not detected as an escape; "
        "the suite cannot fail and therefore proves nothing"
    )


def test_a_harmless_in_workspace_write_is_not_reported_as_an_escape(tmp_path: Path) -> None:
    """The mirror: a suite that flags everything is as useless as one that flags nothing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside" / f"{CANARY}.txt"
    results = run_attempts(
        workspace,
        outside,
        [
            Attempt(
                "legitimate write",
                "write_file",
                {"path": "notes.txt", "content": "hello"},
                # Succeeding here is ordinary work, not a breach.
                escape_on_success=False,
            )
        ],
    )
    assert results[0].escaped is False
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"


# --- the CI entry point -----------------------------------------------------


def test_the_ci_script_passes() -> None:
    path = _ROOT / "scripts" / "sandbox_escape_check.py"
    spec = importlib.util.spec_from_file_location("sandbox_escape_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
