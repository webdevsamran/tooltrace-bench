"""A conformance report for an MCP server, with severities that mean something.

MCP has effectively won the agent-to-tool layer — roughly 97 million monthly SDK
downloads by February 2026, adopted by every major provider — which makes "does
this server behave correctly" a question a lot of people now have and few can
answer.

`conformance_check` in `tooltrace/agents/mcp.py` already exercised
initialize / tools-list / echo / unknown-tool against the bundled fixture. It
was reachable only from Python, and it graded every check as equally fatal, so
a server that merely lacked a tool description failed identically to one that
never completed a handshake.

This module makes the suite usable and gradates it:

- **`required`** — the server does not work. A client cannot proceed.
- **`recommended`** — the spec asks for it and a good client copes without it.
  A server can be usable and still miss these, and reporting that as failure
  would make the report an opinion rather than a measurement.

Conformance is reported as `required_ok` and `recommended_ok` separately, and
`ok` means required only. Anything else would let a cosmetic gap read as a
protocol violation, or hide a real one behind a passing total.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tooltrace.agents.mcp import MCPClient

REQUIRED = "required"
RECOMMENDED = "recommended"


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity,
            "passed": self.passed,
            "detail": self.detail,
        }


def _text_of(result: dict[str, Any]) -> str:
    content = (result.get("result") or {}).get("content") or []
    if content and isinstance(content[0], dict):
        return str(content[0].get("text", ""))
    return ""


def run_checks(command: list[str], *, timeout_note: str = "") -> list[CheckResult]:
    """Exercise a server over stdio and return one result per check."""
    results: list[CheckResult] = []
    client = MCPClient(command)

    try:
        info = client.start()
    except Exception as exc:
        return [
            CheckResult(
                "initialize", REQUIRED, False, f"handshake failed: {type(exc).__name__}: {exc}"
            )
        ]

    try:
        server_info = info.get("serverInfo") or {}
        results.append(
            CheckResult(
                "initialize",
                REQUIRED,
                bool(server_info),
                f"serverInfo: {server_info.get('name', '(missing)')}",
            )
        )
        results.append(
            CheckResult(
                "initialize_reports_protocol_version",
                REQUIRED,
                bool(info.get("protocolVersion")),
                f"protocolVersion: {info.get('protocolVersion', '(missing)')}",
            )
        )
        results.append(
            CheckResult(
                "initialize_declares_capabilities",
                RECOMMENDED,
                isinstance(info.get("capabilities"), dict),
                "a client cannot know what is supported without this",
            )
        )
        results.append(
            CheckResult(
                "server_reports_version",
                RECOMMENDED,
                bool(server_info.get("version")),
                "an unversioned server cannot be pinned by a caller",
            )
        )

        try:
            tools = client.list_tools()
        except Exception as exc:
            results.append(
                CheckResult("tools_list", REQUIRED, False, f"{type(exc).__name__}: {exc}")
            )
            tools = []
        else:
            results.append(
                CheckResult(
                    "tools_list", REQUIRED, isinstance(tools, list), f"{len(tools)} tool(s)"
                )
            )

        named = [t for t in tools if isinstance(t, dict) and t.get("name")]
        results.append(
            CheckResult(
                "every_tool_has_a_name",
                REQUIRED,
                len(named) == len(tools),
                f"{len(named)} of {len(tools)} tools are named",
            )
        )
        described = [t for t in named if t.get("description")]
        results.append(
            CheckResult(
                "every_tool_has_a_description",
                RECOMMENDED,
                len(described) == len(named),
                # A model choosing between tools reads descriptions; an absent
                # one is a real usability problem, but not a protocol break.
                f"{len(described)} of {len(named)} tools describe themselves",
            )
        )
        with_schema = [t for t in named if isinstance(t.get("inputSchema"), dict)]
        results.append(
            CheckResult(
                "every_tool_declares_an_input_schema",
                RECOMMENDED,
                len(with_schema) == len(named),
                f"{len(with_schema)} of {len(named)} tools declare inputSchema",
            )
        )

        if named:
            first = named[0]["name"]
            try:
                call = client.call_tool(str(first), {})
                results.append(
                    CheckResult(
                        "tools_call_responds",
                        REQUIRED,
                        call.get("status") in {"ok", "error"},
                        f"calling {first!r} returned status {call.get('status')!r}",
                    )
                )
            except Exception as exc:
                results.append(
                    CheckResult(
                        "tools_call_responds", REQUIRED, False, f"{type(exc).__name__}: {exc}"
                    )
                )

        try:
            unknown = client.call_tool("tooltrace_no_such_tool_probe", {})
            results.append(
                CheckResult(
                    "unknown_tool_is_an_error",
                    REQUIRED,
                    unknown.get("status") == "error",
                    # A server that invents a result for a tool it does not have
                    # is worse than one that errors: a client cannot tell.
                    "a server must not answer for a tool it does not have",
                )
            )
        except Exception as exc:
            results.append(
                CheckResult(
                    "unknown_tool_is_an_error", REQUIRED, False, f"{type(exc).__name__}: {exc}"
                )
            )

        try:
            unknown_method = client._request("tooltrace/no_such_method", {})
            results.append(
                CheckResult(
                    "unknown_method_is_an_error",
                    RECOMMENDED,
                    False,
                    f"server answered an unknown method: {str(unknown_method)[:80]}",
                )
            )
        except Exception:
            # Raising is the correct behaviour: the client surfaces the error.
            results.append(
                CheckResult(
                    "unknown_method_is_an_error", RECOMMENDED, True, "unknown method rejected"
                )
            )
    finally:
        client.stop()

    if timeout_note:
        results.append(CheckResult("note", RECOMMENDED, True, timeout_note))
    return results


def report(command: list[str]) -> dict[str, Any]:
    """Full conformance report, with required and recommended kept apart."""
    results = run_checks(command)
    required = [r for r in results if r.severity == REQUIRED]
    recommended = [r for r in results if r.severity == RECOMMENDED]
    required_failures = [r for r in required if not r.passed]
    recommended_failures = [r for r in recommended if not r.passed]

    return {
        # `ok` is required-only. A cosmetic gap must not read as a protocol
        # violation, and a real violation must not hide behind a passing total.
        "ok": not required_failures,
        "required_ok": not required_failures,
        "recommended_ok": not recommended_failures,
        "checks": [r.to_dict() for r in results],
        "required_failures": [r.name for r in required_failures],
        "recommended_failures": [r.name for r in recommended_failures],
        "counts": {
            "required": len(required),
            "recommended": len(recommended),
            "passed": sum(1 for r in results if r.passed),
        },
    }
