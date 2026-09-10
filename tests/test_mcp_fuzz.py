"""Fuzzing an MCP server, and the three crashes it found in this repo's own fixture.

`mcp_conformance` asks a server to do things correctly. This asks it to do things
incorrectly, which is the half that finds real defects — a server is written
against the happy path and tested against the happy path.

It proved that immediately. The first run against `FAKE_SERVER_SCRIPT` crashed it
three times: `json.loads` was unguarded, and `tools/call` reached straight into
`msg["params"]["name"]` without checking that `params` was a mapping or that
`name` was present. That fixture is the **default target of `tooltrace
mcp-conformance`** — the example this project holds up as a conforming server —
so a reference server dying on a truncated line mattered more than a fixture bug
usually would.

The tests below pin both directions. A deliberately fragile server must be
caught, or the fuzzer is decoration; and the hardened fixture must pass, or the
fuzzer is noise. The first matters more: a fuzzer that finds nothing is
indistinguishable from a working system, which is exactly the trap this
repository keeps falling into.
"""

from __future__ import annotations

import json
import sys

import pytest
from tooltrace.agents.mcp import fake_server_command
from tooltrace.agents.mcp_fuzz import (
    CASES,
    CRASHED,
    MAY_REJECT,
    MUST_REJECT,
    REJECTED,
    SHOULD_REJECT,
    FuzzCase,
    fuzz,
    render_markdown,
)
from tooltrace.cli.main import main

#: The fixture as it was: no guards anywhere. Kept verbatim as the thing the
#: fuzzer has to catch, because a fuzzer is only worth its runtime if a broken
#: server fails it.
FRAGILE_SERVER = r"""
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
    if method == "tools/call":
        name = msg["params"]["name"]
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": []}})
    else:
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
"""

#: A server that answers everything, including things it must reject.
PERMISSIVE_SERVER = r"""
import json, sys
def send(obj):
    sys.stdout.write(json.dumps(obj) + "\x0a"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        send({"jsonrpc": "2.0", "id": None, "result": {"sure": True}})
        continue
    ident = msg.get("id") if isinstance(msg, dict) else 1
    send({"jsonrpc": "2.0", "id": ident, "result": {"sure": True}})
"""


def command_for(script: str) -> list[str]:
    return [sys.executable, "-c", script]


@pytest.fixture(scope="module")
def bundled() -> dict:
    return fuzz(fake_server_command())


@pytest.fixture(scope="module")
def fragile() -> dict:
    return fuzz(command_for(FRAGILE_SERVER))


@pytest.fixture(scope="module")
def permissive() -> dict:
    return fuzz(command_for(PERMISSIVE_SERVER))


# --- it catches a broken server ---------------------------------------------


def test_an_unguarded_server_is_caught(fragile: dict) -> None:
    """The three crashes this found in this project's own fixture."""
    assert fragile["ok"] is False
    assert fragile["crashes"], "an unguarded json.loads must be caught"


def test_a_truncated_line_that_crashes_is_a_problem(fragile: dict) -> None:
    case = next(c for c in fragile["cases"] if c["case"] == "truncated_json")
    assert case["outcome"] == CRASHED
    assert case["problem"] is True


def test_reaching_into_missing_params_is_caught(fragile: dict) -> None:
    case = next(c for c in fragile["cases"] if c["case"] == "tools_call_without_a_name")
    assert case["outcome"] == CRASHED


def test_a_server_that_answers_everything_is_caught(permissive: dict) -> None:
    """Accepting a must-reject case is a protocol violation, not tolerance."""
    assert permissive["ok"] is False
    assert "no_method" in permissive["problems"]


# --- ...and the hardened fixture passes -------------------------------------


def test_the_bundled_fixture_no_longer_crashes(bundled: dict) -> None:
    """It is the default target of `mcp-conformance`, so it is the example."""
    assert bundled["crashes"] == []
    assert bundled["ok"] is True


def test_the_fixture_rejects_every_must_reject_case(bundled: dict) -> None:
    for case in bundled["cases"]:
        if case["severity"] == MUST_REJECT:
            assert case["outcome"] in (REJECTED, "no_reply"), (
                f"{case['case']} was {case['outcome']}: {case['why']}"
            )


# --- severity semantics -----------------------------------------------------


def test_tolerating_a_should_reject_case_is_not_a_failure(bundled: dict) -> None:
    """Half the servers in the wild are Postel's-law tolerant.

    Calling that a failure would make this report an opinion rather than a
    measurement, so it is reported and does not fail.
    """
    assert bundled["tolerated_violations"], "the fixture is tolerant, and that is fine"
    assert bundled["ok"] is True
    assert "sloppy rather than broken" in bundled["statement"]


def test_a_may_reject_case_never_produces_a_problem_either_way(bundled: dict) -> None:
    for case in bundled["cases"]:
        if case["severity"] == MAY_REJECT and case["outcome"] != CRASHED:
            assert case["problem"] is False


def test_a_crash_is_a_problem_whatever_the_severity_says() -> None:
    """A server that dies on optional input is still a denial-of-service surface."""
    crashing_on_a_may_case = r"""
import json, sys
for line in sys.stdin:
    if line.strip().startswith("["):
        raise SystemExit(1)
    sys.stdout.write('{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"no"}}\n')
    sys.stdout.flush()
"""
    report = fuzz(
        command_for(crashing_on_a_may_case),
        cases=(FuzzCase("bare_array", MAY_REJECT, '["not", "an", "object"]', "optional"),),
    )
    assert report["ok"] is False
    assert report["crashes"] == ["bare_array"]


def test_every_case_declares_why_it_matters() -> None:
    """A finding with no rationale is a finding nobody can act on."""
    for case in CASES:
        assert case.why, f"{case.name} has no rationale"
        assert case.severity in {MUST_REJECT, SHOULD_REJECT, MAY_REJECT}


def test_the_cases_are_specific_rather_than_random() -> None:
    """Random bytes mostly produce parse errors, which tell you nothing."""
    names = {c.name for c in CASES}
    assert {"no_method", "method_is_not_a_string", "params_is_a_string"} <= names


# --- it terminates ----------------------------------------------------------


def test_a_silent_server_does_not_hang_the_fuzzer() -> None:
    """The first version blocked on `readline` and never returned.

    A deadline checked *between* blocking reads is not a deadline. Closing stdin
    after the write is what makes a silent case end.
    """
    silent = "import sys\nfor line in sys.stdin:\n    pass\n"
    report = fuzz(
        command_for(silent), cases=(FuzzCase("silent", MUST_REJECT, "{}", "no reply at all"),)
    )
    assert report["cases"][0]["outcome"] in ("no_reply", CRASHED)


def test_a_server_that_will_not_start_is_reported_not_raised() -> None:
    report = fuzz(
        ["definitely-not-a-real-binary-xyz"],
        cases=(FuzzCase("any", MUST_REJECT, "{}", "cannot start"),),
    )
    assert report["cases"][0]["outcome"] == CRASHED
    assert "could not start" in report["cases"][0]["detail"]


# --- rendering and the CLI --------------------------------------------------


def test_the_rendering_calls_out_a_crash(fragile: dict) -> None:
    rendered = render_markdown(fragile)
    assert "denial-of-service surface" in rendered


def test_a_clean_report_does_not_mention_denial_of_service(bundled: dict) -> None:
    assert "denial-of-service" not in render_markdown(bundled)


def test_the_cli_passes_the_bundled_fixture(capsys) -> None:
    assert main(["mcp-fuzz", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_the_cli_fails_a_fragile_server(capsys) -> None:
    code = main(["mcp-fuzz", "--json", "--", *command_for(FRAGILE_SERVER)])
    captured = capsys.readouterr()
    assert code != 0
    assert "problem(s)" in captured.err
