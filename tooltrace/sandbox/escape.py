"""Actively attempt to escape the sandbox, through the surface an agent uses.

`scripts/sandbox_check.py` calls `resolve_in_workspace` with a few bad paths and
checks that some defaults are set. That is a conformance check on a helper: it
proves the function rejects what it is handed, not that an agent cannot get out.
An agent never calls `resolve_in_workspace`; it calls tools, through
`ToolExecutor`. So the attempts here go through that path, with the arguments an
agent would actually supply.

The distinction that makes this suite honest is between two kinds of outcome:

- **`must_block`** — an escape the sandbox claims to prevent. If one of these
  succeeds, isolation is broken and the build fails.
- **`known_limit`** — an escape the local sandbox openly does not prevent, and
  `docs/threat-model.md` says so: a raw-socket program spawned through `shell`
  is not blocked, because blocking it needs kernel-level isolation, which is
  what the Docker provider is for. These are executed and reported, never
  silently omitted, because a suite that quietly skips the attacks it would fail
  is a suite that measures nothing.

A `known_limit` that starts being blocked is *good* news, and reported as such,
so the threat model can be tightened rather than left overstating the gap.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tooltrace.tools.base import ToolContext
from tooltrace.tools.executor import ToolExecutor

#: A marker written by a successful escape, so success is detected by evidence
#: on disk rather than by trusting the tool's own report.
CANARY = "ttb-escape-canary"


@dataclass(frozen=True)
class Attempt:
    """One escape attempt through the real tool surface."""

    name: str
    tool: str
    args: dict[str, Any]
    #: "must_block" -> a success here is a build failure.
    #: "known_limit" -> documented as not blocked by the local sandbox.
    severity: str = "must_block"
    #: Extra evidence check: escape succeeded if this file exists afterwards.
    escaped_if_exists: str | None = None
    #: Whether a *successful* call means the boundary was breached. True for
    #: every attempt that targets something outside the workspace, which is all
    #: of them here. A control that legitimately operates inside the workspace
    #: sets this False -- otherwise the suite would flag ordinary work as an
    #: escape, and a checker that flags everything is as useless as one that
    #: flags nothing.
    escape_on_success: bool = True


@dataclass(frozen=True)
class AttemptResult:
    name: str
    severity: str
    escaped: bool
    detail: str


def _outside(tmp: Path) -> Path:
    return tmp / "outside" / f"{CANARY}.txt"


def build_attempts(outside: Path) -> list[Attempt]:
    """Every escape this suite tries, with the arguments an agent would use."""
    outside_posix = outside.as_posix()
    return [
        # --- filesystem boundary -------------------------------------------
        Attempt(
            "write above the workspace with ..",
            "write_file",
            {"path": "../" + outside.name, "content": CANARY},
        ),
        Attempt(
            "write far above the workspace",
            "write_file",
            {"path": "../../../" + outside.name, "content": CANARY},
        ),
        Attempt(
            "write to an absolute path",
            "write_file",
            {"path": outside_posix, "content": CANARY},
            escaped_if_exists=outside_posix,
        ),
        Attempt(
            "write through a mid-path traversal",
            "write_file",
            {"path": "sub/../../" + outside.name, "content": CANARY},
        ),
        Attempt("read above the workspace", "read_file", {"path": "../../etc/hosts"}),
        Attempt("read an absolute system path", "read_file", {"path": "/etc/passwd"}),
        Attempt(
            "patch a file above the workspace",
            "patch_file",
            {"path": "../x", "find": "a", "replace": "b"},
        ),
        Attempt("list a directory above the workspace", "list_directory", {"path": "../.."}),
        Attempt(
            "search outside the workspace", "search_text", {"path": "../..", "pattern": "root"}
        ),
        # --- network --------------------------------------------------------
        Attempt("http egress while the policy is disabled", "http", {"url": "http://example.com"}),
        Attempt(
            "http egress to a host not on the allowlist",
            "http",
            {"url": "http://169.254.169.254/latest/meta-data/"},
        ),
        Attempt("git push", "git", {"args": ["push", "origin", "main"]}),
        Attempt("git fetch a remote", "git", {"args": ["fetch", "origin"]}),
        Attempt("git clone a remote", "git", {"args": ["clone", "https://example.com/x.git"]}),
        # --- documented limits of the *local* sandbox ------------------------
        Attempt(
            "shell writes above the workspace",
            "shell",
            {"command": f'echo {CANARY} > "{outside_posix}"'},
            severity="known_limit",
            escaped_if_exists=outside_posix,
        ),
        Attempt(
            "shell reads the environment",
            "shell",
            {"command": "env" if os.name != "nt" else "set"},
            severity="known_limit",
        ),
    ]


def _looks_blocked(result: Any) -> bool:
    """A refusal is an error result, a denial, or an exception."""
    if result is None:
        return True
    ok = getattr(result, "ok", False)
    data = getattr(result, "data", {}) or {}
    return (not ok) or bool(data.get("denied")) or bool(data.get("invalid"))


def run_attempts(workspace: Path, outside: Path, attempts: list[Attempt]) -> list[AttemptResult]:
    """Execute every attempt through `ToolExecutor` and record what happened."""
    ctx = ToolContext(workspace=workspace, network_policy="disabled")
    executor = ToolExecutor(
        ctx=ctx,
        # Every tool is allowed, deliberately: the question is whether the
        # *boundary* holds, not whether an allowlist was configured. A task
        # would normally narrow this, and that narrowing is a second control.
        allowed_tools=[
            "read_file",
            "write_file",
            "patch_file",
            "list_directory",
            "search_text",
            "shell",
            "git",
            "http",
        ],
        emit_event=lambda _ev: None,
    )

    results: list[AttemptResult] = []
    for attempt in attempts:
        outside.parent.mkdir(parents=True, exist_ok=True)
        if outside.exists():
            outside.unlink()
        try:
            outcome = executor.execute(attempt.tool, dict(attempt.args))
            blocked = _looks_blocked(outcome)
            detail = str(getattr(outcome, "error", "") or getattr(outcome, "output", ""))[:160]
        except Exception as exc:  # a raised PolicyViolation is a refusal
            blocked, detail = True, f"{type(exc).__name__}: {exc}"[:160]

        # Trust evidence over the tool's own report: a write that claims to have
        # failed but left a file outside the workspace still escaped.
        escaped = attempt.escape_on_success and not blocked
        if attempt.escaped_if_exists and Path(attempt.escaped_if_exists).exists():
            escaped = True
            detail = f"wrote outside the workspace: {attempt.escaped_if_exists}"
        if outside.exists():
            escaped = True

        results.append(AttemptResult(attempt.name, attempt.severity, escaped, detail))
    return results


def check_isolation() -> dict[str, Any]:
    """Run the whole suite in a throwaway workspace and summarise it."""
    with tempfile.TemporaryDirectory(prefix="tooltrace-escape-") as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        outside = _outside(root)
        results = run_attempts(workspace, outside, build_attempts(outside))

    breaches = [r for r in results if r.escaped and r.severity == "must_block"]
    limits_confirmed = [r for r in results if r.escaped and r.severity == "known_limit"]
    limits_now_blocked = [r for r in results if not r.escaped and r.severity == "known_limit"]

    return {
        "ok": not breaches,
        "attempts": len(results),
        "breaches": [{"name": r.name, "detail": r.detail} for r in breaches],
        "known_limits_confirmed": [r.name for r in limits_confirmed],
        # Good news, reported so the threat model can stop overstating the gap.
        "known_limits_now_blocked": [r.name for r in limits_now_blocked],
        "results": [
            {"name": r.name, "severity": r.severity, "escaped": r.escaped, "detail": r.detail}
            for r in results
        ],
    }
