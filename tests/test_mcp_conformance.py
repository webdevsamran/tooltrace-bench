"""MCP conformance checks must distinguish a broken server from an untidy one.

MCP has effectively won the agent-to-tool layer, so "does this server behave
correctly" is a question many people now have. `conformance_check` already
existed, but it was reachable only from Python and graded every check as equally
fatal — a server missing a tool *description* failed identically to one that
never completed a handshake. Those are not the same finding, and a report that
conflates them is an opinion rather than a measurement.

So severity is the thing under test here as much as the checks themselves:
`ok` means *required* only, and a deliberately non-conforming server is run to
prove each class of failure is actually detected. A conformance suite that
passes everything it is pointed at measures nothing.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest
from tooltrace.agents.mcp import fake_server_command
from tooltrace.agents.mcp_conformance import RECOMMENDED, REQUIRED, report, run_checks
from tooltrace.cli.main import main

#: A server that completes a handshake and then misbehaves in specific,
#: individually-detectable ways: no capabilities, no server version, a tool with
#: neither description nor inputSchema, and — worst — a fabricated result for a
#: tool it does not have.
SLOPPY_SERVER = r"""
import json, sys
def send(obj):
    sys.stdout.write(json.dumps(obj) + "\x0a"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result":
              {"protocolVersion": "2024-11-05", "serverInfo": {"name": "sloppy"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg["id"], "result":
              {"tools": [{"name": "bare"}]}})
    else:
        # Answers anything, including tools it does not have.
        send({"jsonrpc": "2.0", "id": msg["id"], "result":
              {"content": [{"type": "text", "text": "sure"}]}})
"""


def _sloppy_command() -> list[str]:
    return [sys.executable, "-c", SLOPPY_SERVER]


@pytest.fixture(scope="module")
def good() -> dict[str, Any]:
    return report(fake_server_command())


@pytest.fixture(scope="module")
def sloppy() -> dict[str, Any]:
    return report(_sloppy_command())


# --- a conforming server passes ---------------------------------------------


def test_the_bundled_fixture_conforms(good: dict[str, Any]) -> None:
    assert good["ok"] is True
    assert good["required_failures"] == []
    assert good["recommended_failures"] == []


def test_both_severities_are_actually_exercised(good: dict[str, Any]) -> None:
    """A suite with only required checks could not distinguish anything."""
    assert good["counts"]["required"] >= 5
    assert good["counts"]["recommended"] >= 4


# --- ...and a sloppy one is caught, check by check ---------------------------


def test_a_server_that_answers_for_tools_it_lacks_fails_required(sloppy: dict[str, Any]) -> None:
    """The worst failure mode: a client cannot tell a real result from a made-up one."""
    assert "unknown_tool_is_an_error" in sloppy["required_failures"]
    assert sloppy["ok"] is False


def test_missing_descriptions_and_schemas_are_recommended_not_required(
    sloppy: dict[str, Any],
) -> None:
    """A tool without a description is untidy, not a protocol violation."""
    assert "every_tool_has_a_description" in sloppy["recommended_failures"]
    assert "every_tool_declares_an_input_schema" in sloppy["recommended_failures"]
    assert "every_tool_has_a_description" not in sloppy["required_failures"]


def test_missing_capabilities_and_version_are_recommended(sloppy: dict[str, Any]) -> None:
    assert "initialize_declares_capabilities" in sloppy["recommended_failures"]
    assert "server_reports_version" in sloppy["recommended_failures"]


def test_a_server_that_answers_unknown_methods_is_flagged(sloppy: dict[str, Any]) -> None:
    assert "unknown_method_is_an_error" in sloppy["recommended_failures"]


def test_a_server_that_never_starts_reports_the_handshake_not_a_crash() -> None:
    results = run_checks([sys.executable, "-c", "raise SystemExit(1)"])
    assert results[0].name == "initialize"
    assert results[0].severity == REQUIRED
    assert results[0].passed is False


# --- severity semantics -----------------------------------------------------


def test_ok_means_required_only(sloppy: dict[str, Any]) -> None:
    """A cosmetic gap must not read as a protocol violation, and vice versa."""
    assert sloppy["recommended_ok"] is False
    assert sloppy["required_ok"] == sloppy["ok"]


def test_every_check_declares_a_severity(good: dict[str, Any]) -> None:
    for check in good["checks"]:
        assert check["severity"] in {REQUIRED, RECOMMENDED}
        assert check["detail"], f"{check['name']} gives a reader nothing to act on"


# --- the CLI ----------------------------------------------------------------


def test_the_cli_passes_a_conforming_server(capsys) -> None:
    assert main(["mcp-conformance", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_the_cli_fails_only_on_required_problems(capsys) -> None:
    # `--` first: the server command takes flags of its own, which argparse
    # would otherwise claim. This is the same convention as `docker run`.
    code = main(["mcp-conformance", "--json", "--", *_sloppy_command()])
    captured = capsys.readouterr()
    assert code != 0
    assert "required conformance failures" in captured.err
    assert "unknown_tool_is_an_error" in captured.err


def test_recommended_problems_are_a_note_not_a_failure(capsys, monkeypatch) -> None:
    """A usable-but-untidy server must not be reported as broken."""
    import tooltrace.agents.mcp_conformance as conformance

    real = conformance.report

    def only_recommended_failures(command: list[str]) -> dict[str, Any]:
        result = real(fake_server_command())
        result["recommended_failures"] = ["every_tool_has_a_description"]
        result["recommended_ok"] = False
        return result

    monkeypatch.setattr("tooltrace.agents.mcp_conformance.report", only_recommended_failures)
    assert main(["mcp-conformance", "--json"]) == 0
    assert "misses recommended behaviour" in capsys.readouterr().err
