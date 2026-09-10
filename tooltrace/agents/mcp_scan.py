"""Score many MCP servers at once, and refuse to run what a registry told you to.

`mcp-conformance`, `mcp-fuzz` and `mcp-versions` each answer one question about
one server. The question a team actually has is comparative: of the servers we
are considering, which ones behave, and which fall over on a truncated line.

A scan runs all three against each target and puts the answers in one table.
Nothing here is a new check -- the value is entirely in the batching and in
ordering the result by what a reader has to act on.

## The rule that shapes this file

A target has a `command` or a `url`. A `command` is executed. So:

**A command may only come from a file on this machine.** A registry fetched over
the network contributes URL targets and nothing else. Running a command string
that arrived from a server on the internet is remote code execution with a
progress bar, and the fact that the registry is a reputable one does not change
what the code does -- only how likely it is to be abused today.

The refusal is loud rather than silent: a fetched entry carrying a command is
reported as skipped, with the reason, so a reader knows the scan is incomplete
rather than assuming that server passed.
"""

from __future__ import annotations

from typing import Any

from tooltrace.agents.mcp_conformance import report as conformance_report
from tooltrace.agents.mcp_fuzz import fuzz
from tooltrace.agents.mcp_versions import version_matrix

LOCAL = "local-file"
REMOTE = "registry"

SKIPPED = "skipped"


def _target_name(entry: dict[str, Any], index: int) -> str:
    name = entry.get("name")
    if isinstance(name, str) and name:
        return name
    url = entry.get("url")
    if isinstance(url, str) and url:
        return url
    command = entry.get("command")
    if isinstance(command, list) and command:
        return str(command[0])
    return f"target-{index}"


def scan_one(entry: dict[str, Any], origin: str = LOCAL) -> dict[str, Any]:
    """Conformance, protocol versions and malformed input, against one server."""
    name = _target_name(entry, 0)
    url = entry.get("url") if isinstance(entry.get("url"), str) else None
    command = entry.get("command") if isinstance(entry.get("command"), list) else None

    if command and origin != LOCAL:
        return {
            "name": name,
            "state": SKIPPED,
            "reason": (
                "this entry names a command to execute and it came from a registry rather "
                "than from a file on this machine. Running it would be remote code execution"
            ),
        }
    if not command and not url:
        return {"name": name, "state": SKIPPED, "reason": "the entry names neither url nor command"}

    conformance = conformance_report(command, url=url) if url else conformance_report(command)
    versions = version_matrix(command, url=url) if url else version_matrix(command)
    # Fuzzing needs a process to send raw bytes at; over HTTP the transport
    # frames every message, so the malformed-input cases would be testing httpx
    # rather than the server. Reported as not-run rather than as passed.
    if command:
        malformed: dict[str, Any] | None = fuzz(command)
    else:
        malformed = None

    problems = list(conformance["required_failures"])
    problems += [f"version:{v}" for v in versions["problems"]]
    if malformed:
        problems += [f"malformed:{c}" for c in malformed["problems"]]

    return {
        "name": name,
        "state": "scanned",
        "transport": "http" if url else "stdio",
        "conformance": conformance,
        "versions": versions,
        "malformed": malformed,
        "malformed_note": (
            None
            if malformed
            else "not run: fuzzing sends raw bytes, which an HTTP transport reframes"
        ),
        "problems": problems,
        "ok": not problems,
    }


def scan(targets: list[dict[str, Any]], origin: str = LOCAL) -> dict[str, Any]:
    """Scan every target and rank them by what a reader has to act on."""
    results = [scan_one(entry, origin) for entry in targets]
    scanned = [r for r in results if r["state"] == "scanned"]
    skipped = [r for r in results if r["state"] == SKIPPED]
    failing = [r for r in scanned if not r["ok"]]

    # Worst first. A leaderboard sorted by name buries the one row anybody
    # needed to see.
    ranked = sorted(scanned, key=lambda r: (-len(r["problems"]), r["name"]))

    return {
        "targets": len(targets),
        "scanned": len(scanned),
        "skipped": [{"name": r["name"], "reason": r["reason"]} for r in skipped],
        "results": ranked,
        "ok": not failing,
        "statement": (
            f"{len(scanned)} of {len(targets)} server(s) scanned; "
            + (
                f"{len(failing)} have at least one problem"
                if failing
                else "none had a required failure"
            )
            + (f". {len(skipped)} skipped, which is not the same as passing." if skipped else ".")
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "| Server | Transport | Required failures | Protocol | Malformed input |",
        "|---|---|---|---|---|",
    ]
    for row in report["results"]:
        required = row["conformance"]["required_failures"]
        malformed = row["malformed"]
        malformed_cell = (
            f"{len(malformed['problems'])} problem(s)" if malformed else "not run over HTTP"
        )
        lines.append(
            f"| `{row['name']}` | {row['transport']} | "
            f"{len(required)} | {row['versions']['supported'] or 'none'} | {malformed_cell} |"
        )
    lines += ["", report["statement"]]
    if report["skipped"]:
        lines += ["", "**Skipped**, which is not the same as passing:"]
        lines += [f"- `{s['name']}`: {s['reason']}" for s in report["skipped"]]
    return "\n".join(lines) + "\n"


def targets_from_registry(payload: Any) -> list[dict[str, Any]]:
    """URL targets from a registry document. Commands are dropped on purpose.

    The MCP registry format nests entries under `servers`, each with `remotes`
    carrying a URL and often a `packages` block describing how to run the thing
    locally. Only the first is usable here: see the module docstring.
    """
    entries = payload.get("servers") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    targets: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("id")
        remotes = entry.get("remotes")
        urls = [
            r.get("url")
            for r in (remotes if isinstance(remotes, list) else [])
            if isinstance(r, dict) and isinstance(r.get("url"), str)
        ]
        if not urls and isinstance(entry.get("url"), str):
            urls = [entry["url"]]
        for url in urls:
            targets.append({"name": str(name or url), "url": url})
    return targets
