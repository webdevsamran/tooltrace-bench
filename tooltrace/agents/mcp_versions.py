"""Which MCP protocol versions a server actually implements, and whether it says so.

`mcp_conformance` checks one version -- whichever the client happened to ask
for. That is the wrong question when a server has to interoperate with clients
released over two years. This asks the handshake once per published version and
records what came back.

The interesting outcome is not "supported" or "unsupported". Both are fine, and
a server that answers a version it does not implement with a version it does is
doing exactly what the spec asks. The interesting outcome is a server that
**echoes back whatever it was sent**, including a version that has never
existed. Such a server is not negotiating; it is agreeing. A client then
proceeds believing it settled on a protocol, and the mismatch surfaces later as
a field that is missing for no visible reason.

That is why a deliberately impossible version is in the list. A server cannot
support `9999-01-01`, so any answer other than "no" or "here is what I do
support" is a defect that no amount of testing against real versions would find.
"""

from __future__ import annotations

from typing import Any

from tooltrace.agents.mcp import MCPClient, MCPProtocolError, MCPStartupError

#: Published MCP protocol revisions, oldest first.
KNOWN_VERSIONS: tuple[str, ...] = ("2024-11-05", "2025-03-26", "2025-06-18")

#: Versions no server can implement. Sent to see whether the server is checking
#: at all -- the whole point of the exercise.
IMPOSSIBLE_VERSIONS: tuple[str, ...] = ("9999-01-01", "1.0")

AGREED = "agreed"
DOWNGRADED = "downgraded"
REJECTED = "rejected"
ECHOED_UNKNOWN = "echoed_unknown"
NO_VERSION = "no_version"
CRASHED = "crashed"

#: Outcomes that are a problem. `rejected` is not one: refusing a version you do
#: not implement is the correct answer, and so is answering with one you do.
PROBLEM_OUTCOMES = frozenset({ECHOED_UNKNOWN, NO_VERSION, CRASHED})


def _classify(sent: str, answered: str | None) -> tuple[str, str]:
    if answered is None:
        return NO_VERSION, "the initialize result carried no protocolVersion"
    if answered == sent:
        if sent in KNOWN_VERSIONS:
            return AGREED, f"implements {answered}"
        return (
            ECHOED_UNKNOWN,
            f"echoed {answered!r}, which is not a published revision -- "
            "the server is agreeing rather than negotiating",
        )
    if answered in KNOWN_VERSIONS:
        return DOWNGRADED, f"answered {answered} instead, which is correct negotiation"
    return (
        ECHOED_UNKNOWN,
        f"answered {answered!r}, which is not a published revision",
    )


def version_matrix(
    command: list[str],
    versions: tuple[str, ...] = KNOWN_VERSIONS + IMPOSSIBLE_VERSIONS,
) -> dict[str, Any]:
    """Handshake once per version, on a fresh process each time.

    A fresh process per version for the same reason the fuzzer uses one: a
    server left in a bad state by the third handshake would make the fourth
    measure the damage rather than the input.
    """
    rows: list[dict[str, Any]] = []

    for version in versions:
        client = MCPClient(command, protocol_version=version)
        try:
            result = client.start()
        except (MCPProtocolError, MCPStartupError) as exc:
            # An error *response* is a refusal, which is a legitimate answer to a
            # version you do not implement. A transport failure is not. These
            # were one exception until this module needed to tell them apart,
            # and substring-matching the message classified
            # `[WinError 2] cannot find the file` as a polite refusal.
            outcome = REJECTED if isinstance(exc, MCPProtocolError) else CRASHED
            rows.append(
                {
                    "sent": version,
                    "answered": None,
                    "outcome": outcome,
                    "detail": str(exc)[:160],
                    "problem": outcome in PROBLEM_OUTCOMES,
                }
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive
            rows.append(
                {
                    "sent": version,
                    "answered": None,
                    "outcome": CRASHED,
                    "detail": f"{type(exc).__name__}: {exc}",
                    "problem": True,
                }
            )
            continue

        answered = result.get("protocolVersion")
        answered_text = str(answered) if isinstance(answered, str) else None
        outcome, detail = _classify(version, answered_text)
        rows.append(
            {
                "sent": version,
                "answered": answered_text,
                "outcome": outcome,
                "detail": detail,
                "problem": outcome in PROBLEM_OUTCOMES,
            }
        )
        client.stop()

    supported = sorted({r["sent"] for r in rows if r["outcome"] == AGREED})
    problems = [r["sent"] for r in rows if r["problem"]]
    echoed = [r["sent"] for r in rows if r["outcome"] == ECHOED_UNKNOWN]

    return {
        "versions": rows,
        "supported": supported,
        "problems": problems,
        "ok": not problems,
        "statement": (
            (f"implements {', '.join(supported)}" if supported else "implements no tested revision")
            + (
                f"; agreed to {len(echoed)} version(s) that do not exist, so it is not "
                "checking the field at all"
                if echoed
                else "; refused or downgraded every version it does not implement"
            )
            + "."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["| Sent | Answered | Outcome |", "|---|---|---|"]
    for row in report["versions"]:
        answered = f"`{row['answered']}`" if row["answered"] else "--"
        lines.append(f"| `{row['sent']}` | {answered} | {row['outcome']} |")
    lines += ["", report["statement"]]
    if any(r["outcome"] == ECHOED_UNKNOWN for r in report["versions"]):
        lines += [
            "",
            "**A server that echoes back the version it was sent is agreeing, not "
            "negotiating.** A client proceeds believing it settled on a protocol, and the "
            "mismatch surfaces later as a field that is missing for no visible reason.",
        ]
    return "\n".join(lines) + "\n"
