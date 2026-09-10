"""Fuzz an MCP server with malformed JSON-RPC, and report what it did.

`mcp_conformance` asks a server to do things correctly and checks that it does.
This asks it to do things *incorrectly* and checks that it refuses — which is the
half that finds real defects, because a server is written against the happy path
and tested against the happy path.

The cases are not random bytes. Random fuzzing of a JSON-RPC server mostly
produces parse errors, which every server handles identically and which tell you
nothing. These are the specific malformed shapes a protocol implementation gets
wrong: a missing `jsonrpc` version, an id that is an object, a batch, a method
name that is not a string, arguments of the wrong type, and a request with no
method at all.

Three severities, and the middle one carries the value:

- **`must_reject`** — accepting this is a protocol violation with security
  consequences. A server that answers a request with no `method` is answering
  something it did not understand.
- **`should_reject`** — the spec says no and a tolerant server is merely
  sloppy. Reported, never fatal: half the servers in the wild are Postel's-law
  tolerant and calling that a failure would make the report an opinion.
- **`may_reject`** — either behaviour conforms. Recorded so the report describes
  the server rather than grading it.

**A crash is always a finding.** A server that dies on malformed input is a
denial-of-service surface, whatever the spec says about the input, and that is the
one outcome this module treats as severe regardless of severity class.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

MUST_REJECT = "must_reject"
SHOULD_REJECT = "should_reject"
MAY_REJECT = "may_reject"

#: How long to wait for a reply before deciding the server is not answering.
#: Generous: a slow server is not a broken one, and a false "hung" finding is
#: worse than a slow test.
REPLY_TIMEOUT = 5.0


@dataclass(frozen=True)
class FuzzCase:
    name: str
    severity: str
    #: Raw line sent verbatim. Not a dict, because several cases are things
    #: `json.dumps` cannot produce -- truncated JSON, a duplicate key, a bare
    #: array where an object belongs.
    payload: str
    why: str


CASES: tuple[FuzzCase, ...] = (
    FuzzCase(
        "missing_jsonrpc_version",
        SHOULD_REJECT,
        '{"id": 1, "method": "tools/list", "params": {}}',
        "JSON-RPC 2.0 requires the version field; many servers accept it anyway",
    ),
    FuzzCase(
        "wrong_jsonrpc_version",
        SHOULD_REJECT,
        '{"jsonrpc": "1.0", "id": 1, "method": "tools/list", "params": {}}',
        "a server that answers 1.0 is answering a protocol it does not implement",
    ),
    FuzzCase(
        "no_method",
        MUST_REJECT,
        '{"jsonrpc": "2.0", "id": 1, "params": {}}',
        "answering a request with no method is answering something unparsed",
    ),
    FuzzCase(
        "method_is_not_a_string",
        MUST_REJECT,
        '{"jsonrpc": "2.0", "id": 1, "method": {"nested": "object"}, "params": {}}',
        "a non-string method cannot name anything; dispatching on it is a type confusion",
    ),
    FuzzCase(
        "id_is_an_object",
        SHOULD_REJECT,
        '{"jsonrpc": "2.0", "id": {"not": "scalar"}, "method": "tools/list", "params": {}}',
        "the spec restricts id to a string, number or null",
    ),
    FuzzCase(
        "params_is_a_string",
        MUST_REJECT,
        '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": "not-an-object"}',
        "params must be structured; a string here means the server indexed into a string",
    ),
    FuzzCase(
        "tools_call_without_a_name",
        MUST_REJECT,
        '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}}',
        "calling an unnamed tool is the request that must never succeed",
    ),
    FuzzCase(
        "truncated_json",
        MUST_REJECT,
        '{"jsonrpc": "2.0", "id": 1, "method": "tools/li',
        "a parse error must be an error, not a partial dispatch",
    ),
    FuzzCase(
        "bare_array",
        MAY_REJECT,
        '["not", "an", "object"]',
        "a batch is optional in MCP; either behaviour conforms",
    ),
    FuzzCase(
        "empty_object",
        MUST_REJECT,
        "{}",
        "nothing in an empty object identifies a request",
    ),
    FuzzCase(
        "deeply_nested_params",
        MAY_REJECT,
        '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": '
        + '{"name": "x", "arguments": '
        + '{"a":' * 40
        + "1"
        + "}" * 40
        + "}}",
        "depth limits are an implementation choice; a crash is not",
    ),
    FuzzCase(
        "huge_id",
        MAY_REJECT,
        '{"jsonrpc": "2.0", "id": ' + "9" * 400 + ', "method": "tools/list", "params": {}}',
        "an id larger than the integer type is a parser edge, not a protocol one",
    ),
)

ACCEPTED = "accepted"
REJECTED = "rejected"
NO_REPLY = "no_reply"
CRASHED = "crashed"


def _classify(line: str | None, alive: bool) -> str:
    if not alive:
        return CRASHED
    if line is None:
        return NO_REPLY
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        # A reply that is not JSON is its own kind of broken, and closer to a
        # crash than to a rejection.
        return CRASHED
    if isinstance(message, dict) and "error" in message:
        return REJECTED
    return ACCEPTED


def fuzz(command: list[str], cases: tuple[FuzzCase, ...] = CASES) -> dict[str, Any]:
    """Send each malformed request to a fresh server and record what happened.

    A fresh process per case, deliberately. A server left in a bad state by case
    three would make cases four onwards measure the damage rather than the input,
    and a shared process cannot tell "this input crashed it" from "the previous
    one did".
    """
    results: list[dict[str, Any]] = []

    for case in cases:
        outcome, detail = _send_one(command, case.payload)
        results.append(
            {
                "case": case.name,
                "severity": case.severity,
                "outcome": outcome,
                "why": case.why,
                "detail": detail,
                # A crash is a finding whatever the severity class says: a server
                # that dies on malformed input is a denial-of-service surface.
                "problem": outcome == CRASHED
                or (case.severity == MUST_REJECT and outcome == ACCEPTED),
            }
        )

    problems = [r for r in results if r["problem"]]
    crashes = [r for r in results if r["outcome"] == CRASHED]
    tolerated = [r for r in results if r["severity"] == SHOULD_REJECT and r["outcome"] == ACCEPTED]

    return {
        "cases": results,
        "ok": not problems,
        "problems": [r["case"] for r in problems],
        "crashes": [r["case"] for r in crashes],
        # Reported, never fatal. Half the servers in the wild are tolerant, and
        # calling that a failure would make this report an opinion.
        "tolerated_violations": [r["case"] for r in tolerated],
        "statement": (
            f"{len(problems)} problem(s) across {len(results)} malformed request(s)."
            + (f" {len(crashes)} crashed the server." if crashes else "")
            + (
                f" {len(tolerated)} spec violation(s) were accepted; that is sloppy rather "
                "than broken and does not fail this check."
                if tolerated
                else ""
            )
        ),
    }


def _send_one(command: list[str], payload: str) -> tuple[str, str]:
    """One malformed request against one fresh process.

    Writes the payload, closes stdin, and waits for the process to finish.
    Closing stdin is what makes this terminate: a server looping over stdin sees
    EOF and exits, so a case that produces no reply ends in a second rather than
    blocking forever on `readline`. The first version did block, on the very
    first case, because a deadline checked *between* blocking reads is not a
    deadline at all.
    """
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, ValueError) as exc:
        return CRASHED, f"could not start the server: {type(exc).__name__}: {exc}"

    try:
        stdout, stderr = process.communicate(payload + "\n", timeout=REPLY_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        # Hanging on malformed input is the same denial-of-service surface a
        # crash is, reached from the other direction.
        return CRASHED, f"no reply within {REPLY_TIMEOUT}s and the process did not exit"
    except (OSError, BrokenPipeError) as exc:
        return CRASHED, f"{type(exc).__name__}: {exc}"

    first = next((line for line in stdout.splitlines() if line.strip()), None)
    crashed_out = process.returncode not in (0, None) or _looks_like_a_traceback(stderr)
    outcome = _classify(first, alive=not crashed_out)

    if outcome == CRASHED and crashed_out:
        detail = (stderr.strip().splitlines() or ["exited non-zero"])[-1][:160]
    else:
        detail = (first or "no reply").strip()[:160]
    return outcome, detail


def _looks_like_a_traceback(stderr: str) -> bool:
    """An exception on stderr is a crash even when the exit code hides it.

    A server that catches everything at the top level and exits 0 has still
    fallen over on this input, and a reader chasing a bug report needs to know.
    """
    return "Traceback (most recent call last)" in stderr


def render_markdown(report: dict[str, Any]) -> str:
    """A table for a bug report against someone else's server."""
    lines = [
        "| Case | Severity | Outcome | Problem |",
        "|---|---|---|---|",
    ]
    for row in report["cases"]:
        lines.append(
            f"| `{row['case']}` | {row['severity']} | {row['outcome']} | "
            f"{'yes' if row['problem'] else 'no'} |"
        )
    lines += ["", report["statement"]]
    if report["crashes"]:
        lines += [
            "",
            "**A crash on malformed input is a denial-of-service surface**, whatever the "
            "specification says about the input itself.",
        ]
    return "\n".join(lines) + "\n"
