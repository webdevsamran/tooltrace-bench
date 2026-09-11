"""`--json` has to produce JSON, on every command that has it.

`docs/cli-reference.md` opens with "All commands accept `--json` for structured
output". Several of them printed a human-readable line to stdout first -- "wrote
3 draft task(s) to drafts/" -- so `tooltrace import --json | jq` failed on
exactly the commands most likely to be scripted: the ones that write files.

It is the sort of defect that comes back, because the fix is one `if` in a
branch nobody re-reads. So it is a gate rather than a fix.

Commands needing a live server, a network, or arguments this test cannot
synthesise are listed as exempt with the reason. The list is deliberately short
and shrinking it is an improvement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import build_parser, main

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

#: Commands this test cannot drive, and why. Not a list of commands allowed to
#: emit malformed JSON -- a list of commands nothing here can invoke.
EXEMPT = {
    "server": "binds a port and blocks",
    "serve": "binds a port and blocks",
    "init": "writes into a directory and prompts",
    "run": "needs a task and an agent, covered by its own tests",
    "benchmark": "runs a sweep, covered by its own tests",
    "showdown": "runs several sweeps",
    "perturb": "runs a sweep with fault injection",
    "counterfactual": "runs one sweep per tool",
    "shadow": "needs a recorded trace",
    "ingest": "needs an external trace file",
    "promote-trace": "needs an external trace file",
    "import": "needs records from another benchmark",
    "online": "needs an arrival stream and a state directory",
    "sample": "needs an arrival stream",
    "export": "reads a payload from stdin",
    "compare": "needs two single-run bundles",
    "regression": "needs a baseline and thresholds",
    "pr-report": "needs two bundle directories",
    "baseline": "records a named baseline",
    "attest": "reproduces a bundle",
    "reproduce": "re-runs a bundle",
    "verify": "needs a bundle path",
    "trace": "needs a bundle path",
    "snapshot": "needs a source directory",
    "validate": "needs a pack path",
    "task": "a sub-command group",
    "dry-run": "needs a task id",
    "a2a-card": "needs a card file",
    "mcp-conformance": "starts a server subprocess, covered by its own tests",
    "mcp-fuzz": "starts a server subprocess, covered by its own tests",
    "mcp-versions": "starts a server subprocess, covered by its own tests",
    "mcp-scan": "starts server subprocesses, covered by its own tests",
    "redaction": "needs bundles, covered by its own tests",
    "evidence": "needs bundles, covered by its own tests",
    "platforms": "needs bundles, covered by its own tests",
    "card": "needs bundles",
    "self-audit": "needs bundles",
    "drift": "needs two windows of bundles",
    "cost": "needs bundles",
    "hardware": "probes the machine, covered by its own tests",
    "badge": "needs a summary or bundles",
    "report": "needs bundles",
    "power": "covered by its own tests",
    "fleet": "a sub-command group needing a queue directory, covered by tests/test_shard_merge_sign.py",
    "merge": "needs shard directories, covered by tests/test_shard_merge_sign.py",
    "sign": "needs bundle paths, covered by tests/test_shard_merge_sign.py",
}


def commands() -> list[str]:
    import argparse

    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    return sorted(subparsers[0].choices)


NO_ARG_COMMANDS = [name for name in commands() if name not in EXEMPT]


def test_there_is_something_left_to_check() -> None:
    """An exemption list that covered everything would make this test vacuous."""
    assert len(NO_ARG_COMMANDS) >= 5, NO_ARG_COMMANDS


@pytest.mark.parametrize("command", NO_ARG_COMMANDS)
def test_json_output_parses(command: str, capsys) -> None:
    """Whatever the exit code.

    A non-zero exit is often correct -- `lint` exits 3 when it finds something,
    and that is the whole point of it. What must never happen is that the
    caller who piped the output cannot read the findings that caused it.
    """
    main([command, "--json"])
    json.loads(capsys.readouterr().out)  # raises if anything non-JSON came first


@pytest.mark.parametrize("command", NO_ARG_COMMANDS)
def test_json_output_is_an_object_or_a_list(command: str, capsys) -> None:
    """A bare string is technically JSON and useless to a caller piping it."""
    main([command, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict | list), f"{command} emitted {type(payload).__name__}"


def test_every_exemption_names_a_real_command() -> None:
    """An exemption for a command that no longer exists silently widens the list."""
    known = set(commands())
    stale = set(EXEMPT) - known
    assert not stale, f"exemptions for commands that do not exist: {sorted(stale)}"


def test_every_exemption_gives_a_reason() -> None:
    for command, reason in EXEMPT.items():
        assert len(reason) > 5, command


# --- the specific regression --------------------------------------------------


def test_a_file_writing_command_still_emits_only_json(tmp_path: Path, capsys) -> None:
    """`import` wrote "wrote 1 draft task(s) to ..." before its JSON.

    This is the shape of the bug: the commands that write files are the ones
    most likely to be scripted, and they were the ones that broke.
    """
    source = tmp_path / "records.jsonl"
    source.write_text(json.dumps({"instance_id": "x", "repo": "a/b"}), encoding="utf-8")
    code = main(
        [
            "import",
            "--format",
            "swe-bench",
            "--source",
            str(source),
            "--out",
            str(tmp_path / "d"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"] == 1
    assert (tmp_path / "d").is_dir(), "the file was still written"


def test_the_same_command_still_says_so_without_json(tmp_path: Path, capsys) -> None:
    """Silencing the message for everyone would trade one annoyance for another."""
    source = tmp_path / "records.jsonl"
    source.write_text(json.dumps({"instance_id": "x", "repo": "a/b"}), encoding="utf-8")
    main(["import", "--format", "swe-bench", "--source", str(source), "--out", str(tmp_path / "d")])
    assert "wrote" in capsys.readouterr().out
