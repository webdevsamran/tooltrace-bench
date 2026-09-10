"""Scanning many MCP servers, and the one thing a scanner must not do.

The checks here are not new -- conformance, protocol versions and malformed
input each already ship. The value is comparative: of the servers a team is
considering, which behave and which fall over on a truncated line, in one table
ordered worst-first, because a leaderboard sorted by name buries the row anybody
needed to see.

The rule worth testing hardest is the refusal. A target may carry a `command`,
and a command is executed. A registry fetched over the network is therefore
allowed to contribute URL targets and nothing else: running a command string
that arrived from a server on the internet is remote code execution, and the
registry being a reputable one changes how likely that is to be abused, not what
the code does. The refusal is loud, because a silently dropped entry reads as a
server that passed.
"""

from __future__ import annotations

import json
import sys

from tooltrace.agents.mcp import FAKE_SERVER_SCRIPT, fake_server_command
from tooltrace.agents.mcp_http_fixture import FixtureServer
from tooltrace.agents.mcp_scan import LOCAL, REMOTE, render_markdown, scan, targets_from_registry
from tooltrace.cli.main import main

#: The fixture as it was before it was hardened: crashes on a truncated line.
#:
#: Derived from the real script rather than copied, so it cannot drift out of
#: date -- and asserted to have actually changed, because a `str.replace` whose
#: anchor has moved is a silent no-op. That exact failure shipped an
#: undocumented command in this repository earlier the same day.
_GUARD = (
    "    try:\n        msg = json.loads(line)\n    except ValueError:\n"
    '        fail(None, -32700, "parse error")\n        continue\n'
)
FRAGILE = FAKE_SERVER_SCRIPT.replace(_GUARD, "    msg = json.loads(line)\n")
assert FRAGILE != FAKE_SERVER_SCRIPT, "the guard this fixture removes has moved; update _GUARD"


# --- the refusal ------------------------------------------------------------


def test_a_command_from_a_registry_is_never_executed() -> None:
    entry = {"name": "hostile", "command": [sys.executable, "-c", "print('pwned')"]}
    result = scan([entry], REMOTE)
    assert result["scanned"] == 0
    assert result["skipped"][0]["name"] == "hostile"
    assert "remote code execution" in result["skipped"][0]["reason"]


def test_the_same_command_from_a_local_file_is_run() -> None:
    """The boundary is where the entry came from, not what it says."""
    result = scan([{"name": "bundled", "command": fake_server_command()}], LOCAL)
    assert result["scanned"] == 1
    assert result["ok"] is True


def test_a_skipped_entry_is_reported_rather_than_dropped() -> None:
    """A silent drop reads as a pass, which is the opposite of the truth."""
    result = scan(
        [
            {"name": "bundled", "command": fake_server_command()},
            {"name": "hostile", "command": ["anything"]},
        ],
        REMOTE,
    )
    assert "not the same as passing" in result["statement"]
    assert "hostile" in render_markdown(result)


def test_an_entry_naming_neither_url_nor_command_is_skipped() -> None:
    result = scan([{"name": "empty"}], LOCAL)
    assert result["skipped"][0]["reason"].startswith("the entry names neither")


# --- what a registry document contributes -----------------------------------


def test_a_registry_document_yields_urls_only() -> None:
    payload = {
        "servers": [
            {
                "name": "weather",
                "remotes": [{"type": "streamable-http", "url": "https://mcp.example/weather"}],
                "packages": [{"registryType": "npm", "identifier": "weather-mcp"}],
            }
        ]
    }
    targets = targets_from_registry(payload)
    assert targets == [{"name": "weather", "url": "https://mcp.example/weather"}]
    assert all("command" not in t for t in targets)


def test_a_registry_entry_with_no_remote_contributes_nothing() -> None:
    """A locally-installable-only server cannot be scanned from a registry."""
    payload = {"servers": [{"name": "local-only", "packages": [{"identifier": "x"}]}]}
    assert targets_from_registry(payload) == []


def test_a_malformed_registry_document_is_empty_rather_than_an_error() -> None:
    assert targets_from_registry({"unexpected": True}) == []
    assert targets_from_registry("not a document") == []


# --- the scan itself --------------------------------------------------------


def test_a_broken_server_is_ranked_above_a_working_one() -> None:
    """Worst first: a table sorted by name buries the row that mattered."""
    result = scan(
        [
            {"name": "good", "command": fake_server_command()},
            {"name": "fragile", "command": [sys.executable, "-c", FRAGILE]},
        ],
        LOCAL,
    )
    assert result["ok"] is False
    assert result["results"][0]["name"] == "fragile"
    assert any(p.startswith("malformed:") for p in result["results"][0]["problems"])


def test_an_http_target_is_scanned_without_the_fuzzer() -> None:
    """Fuzzing sends raw bytes, which an HTTP transport reframes.

    Running it anyway would test httpx rather than the server, so it is reported
    as not-run instead of quietly counting as a pass.
    """
    with FixtureServer("json") as server:
        result = scan([{"name": "hosted", "url": server.url}], LOCAL)
    row = result["results"][0]
    assert row["transport"] == "http"
    assert row["malformed"] is None
    assert "reframes" in row["malformed_note"]
    assert "not run over HTTP" in render_markdown(result)


def test_a_server_that_will_not_start_is_a_problem_not_a_crash() -> None:
    result = scan([{"name": "missing", "command": ["definitely-not-a-real-binary-xyz"]}], LOCAL)
    assert result["ok"] is False
    assert result["results"][0]["problems"]


def test_a_target_with_no_name_is_still_identifiable() -> None:
    result = scan([{"url": "http://127.0.0.1:1/mcp"}], LOCAL)
    assert result["results"][0]["name"] == "http://127.0.0.1:1/mcp"


# --- the CLI ----------------------------------------------------------------


def test_the_cli_scans_a_local_file(tmp_path, capsys) -> None:
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps([{"name": "bundled", "command": fake_server_command()}]), encoding="utf-8"
    )
    assert main(["mcp-scan", "--from", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scanned"] == 1


def test_the_cli_exits_non_zero_when_a_server_has_a_problem(tmp_path, capsys) -> None:
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps([{"name": "fragile", "command": [sys.executable, "-c", FRAGILE]}]),
        encoding="utf-8",
    )
    assert main(["mcp-scan", "--from", str(path), "--json"]) != 0
    capsys.readouterr()


def test_the_cli_reports_a_missing_file(capsys) -> None:
    assert main(["mcp-scan", "--from", "no-such-file.json"]) != 0
    assert "no such file" in capsys.readouterr().err


def test_the_cli_requires_a_source(capsys) -> None:
    """`--from` and `--registry` differ in what they are trusted to contain."""
    try:
        main(["mcp-scan"])
    except SystemExit as exc:
        assert exc.code != 0
    capsys.readouterr()
