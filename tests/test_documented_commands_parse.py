"""Every `tooltrace` command in the documentation has to be a real command.

The 0.3.0 changelog records this exact failure: the quickstart named a task id
that did not exist and a `--pack` flag the CLI never had. It was found by hand,
after release, by someone trying to follow it -- and the fix was to correct the
text rather than to make the text checkable. Twenty documented invocations later,
nothing verified any of them.

This checks the half that can be checked everywhere: **does the command parse?**
Every documented invocation is fed to the real argument parser, which fails on a
subcommand that does not exist and on a flag that was renamed or removed. That
is precisely the class of rot that shipped before.

It deliberately does not *execute* most of them. A documented command that needs
bundles, a server or an API key cannot run in a unit test, and pretending
otherwise would produce a suite that is either flaky or vacuous. The ones that
are self-contained do run, and the list is at the bottom.

`scripts/cli_smoke.py` runs a hand-maintained list of commands. This runs the
documented ones, which is a different set and the one users actually type.
"""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

import pytest
from tooltrace.cli.main import build_parser

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

#: A fenced block, and its language tag.
FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

#: Placeholders a reader is expected to substitute. A command containing one
#: cannot be parsed for values, but its *flags* still can be.
PLACEHOLDER = re.compile(r"<[^>]+>|\{[^}]+\}|\.\.\.")


def _clean(line: str) -> str:
    r"""One shell line reduced to the command a user would actually run.

    The documentation is written for people, so its examples carry the things
    people write: trailing `# what this does` comments, `\` continuations, a
    backgrounding `&`, and pipes into `jq`. Feeding any of those to argparse
    tests the extractor rather than the documentation.
    """
    line = line.strip().removeprefix("$ ").strip()
    # A comment, but only outside quotes -- `--body '{"a": "#1"}'` is not one.
    out, quote = [], ""
    for char in line:
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "#":
            break
        out.append(char)
    line = "".join(out)
    # The first stage of a pipeline is the part this project owns. `>` counts
    # only when it redirects -- with a space around it -- because a bare one
    # appears inside placeholders like `<bundle>`, and truncating there would
    # report a correct command as malformed.
    for separator in ("|", " > ", " >> ", "&&"):
        line = line.split(separator)[0]
    return line.rstrip(r"&\ ").strip()


def documented_commands() -> list[tuple[str, str]]:
    r"""(source file, command line) for every `tooltrace ...` invocation in a shell block.

    Continuations are joined first: a command split across three lines with
    `\` is one command, and checking each fragment separately would report
    two-thirds of it as nonsense.
    """
    found: list[tuple[str, str]] = []
    for path in DOCS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for language, body in FENCE.findall(text):
            if language not in {"bash", "sh", "shell", "console", ""}:
                continue
            joined: list[str] = []
            buffer = ""
            for raw in body.splitlines():
                stripped = raw.strip()
                if stripped.endswith("\\"):
                    buffer += stripped[:-1].strip() + " "
                    continue
                joined.append(buffer + stripped)
                buffer = ""
            if buffer:
                joined.append(buffer)

            for raw in joined:
                line = _clean(raw)
                if line.startswith("tooltrace "):
                    found.append((path.name, line))
    return found


COMMANDS = documented_commands()


def test_the_documentation_actually_contains_examples() -> None:
    """A zero-length list would make every test below pass vacuously."""
    assert len(COMMANDS) >= 10, f"only found {len(COMMANDS)}"


def known_subcommands() -> set[str]:
    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    return set(subparsers[0].choices)


@pytest.mark.parametrize(("source", "command"), COMMANDS, ids=[f"{s}: {c}" for s, c in COMMANDS])
def test_the_subcommand_exists(source: str, command: str) -> None:
    """The failure that shipped in 0.3.0, in its simplest form."""
    parts = shlex.split(command)
    assert parts[0] == "tooltrace"
    assert len(parts) > 1, f"{source}: `{command}` names no subcommand"
    assert parts[1] in known_subcommands(), f"{source}: `{parts[1]}` is not a command"


@pytest.mark.parametrize(("source", "command"), COMMANDS, ids=[f"{s}: {c}" for s, c in COMMANDS])
def test_every_flag_exists(source: str, command: str) -> None:
    """A renamed flag is the other half of the same rot.

    Parsed rather than string-matched: the parser is the thing that will reject
    it when a user types it, so it is the thing that should reject it here.
    """
    parts = shlex.split(command)
    if PLACEHOLDER.search(command):
        # Values are placeholders, so the command cannot be parsed as written.
        # The flags still can be: check each long option against the
        # subcommand's parser rather than skipping the line entirely.
        subparser = _subparser_for(parts[1])
        known_flags = {option for action in subparser._actions for option in action.option_strings}
        for token in parts[2:]:
            if token.startswith("--"):
                flag = token.split("=")[0]
                assert flag in known_flags, f"{source}: `{flag}` is not an option of `{parts[1]}`"
        return

    parser = build_parser()
    try:
        parser.parse_args(parts[1:])
    except SystemExit as exit_code:
        # argparse exits 0 for `--help`, which is a documented invocation that
        # works. Anything else is a subcommand or a flag the CLI does not have.
        if exit_code.code not in (0, None):
            pytest.fail(f"{source}: `{command}` does not parse (argparse exit {exit_code.code})")


def _subparser_for(name: str) -> argparse.ArgumentParser:
    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    return subparsers[0].choices[name]


# --- the ones that can actually be run --------------------------------------

#: Documented commands that are self-contained: no bundles, no server, no keys,
#: no writes outside a temp directory. Kept short and honest -- a longer list
#: would be better, and inventing one by stubbing the world would not.
RUNNABLE = ("tasks", "agents", "tools", "doctor", "self-test", "owasp", "lint")


@pytest.mark.parametrize("subcommand", RUNNABLE)
def test_a_self_contained_documented_command_runs(subcommand: str, capsys) -> None:
    from tooltrace.cli.main import main

    documented = {parts[1] for _source, command in COMMANDS if (parts := shlex.split(command))}
    if subcommand not in documented:
        pytest.skip(f"`{subcommand}` is not currently documented in a shell block")
    code = main([subcommand, "--json"])
    capsys.readouterr()
    # `lint` exits 3 on findings, which is correct behaviour rather than a
    # broken example.
    assert code in (0, 3), f"`tooltrace {subcommand}` exited {code}"


def test_the_runnable_list_is_not_empty_in_practice() -> None:
    """If nothing documented is runnable, the section above is decoration."""
    documented = {parts[1] for _source, command in COMMANDS if (parts := shlex.split(command))}
    assert documented & set(RUNNABLE), f"documented commands: {sorted(documented)}"
