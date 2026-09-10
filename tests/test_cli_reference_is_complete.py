"""Every command the CLI registers is in the reference, and vice versa.

This gate exists because it was already needed. `tooltrace backends` shipped
with a documentation edit that anchored on a line which was not in the file, so
the edit matched nothing and wrote nothing -- and the command reached `main`
undocumented with every other check green. `docs/cli-reference.md` was the one
document in this repository that nothing verified.

Both directions matter, and for different reasons. An undocumented command is
invisible: it exists, works, and nobody finds it. A documented command that does
not exist is worse, because a reader who types it gets an argparse error and has
to decide which of the two sources is lying.

What this does **not** check is whether the flags in a row are real or the prose
is accurate. Those are worth having and this is worth having first: the failure
it catches is total, not cosmetic.
"""

from __future__ import annotations

import argparse
import pathlib
import re

from tooltrace.cli.main import build_parser

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "cli-reference.md"

#: Commands deliberately absent from the reference. Empty, and a change that
#: needs to add to it should say why here rather than in a commit message.
EXEMPT: frozenset[str] = frozenset()


def registered_commands() -> set[str]:
    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    assert subparsers, "the CLI has no subcommands, which means this test is testing nothing"
    return set(subparsers[0].choices)


def documented_commands() -> set[str]:
    """Every backtick-quoted command name in the first cell of a table row.

    A cell can name more than one command -- `validate --path PACK` and `task
    validate/test/scaffold` share a row -- so each backticked run is read and the
    first word of it taken as the command.

    The split is on *unescaped* pipes. Several rows spell alternatives as
    `--format json\\|csv`, and splitting on those too cuts the cell in half
    mid-backtick, which silently drops the command name and reports a documented
    command as missing.
    """
    found: set[str] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cell = re.split(r"(?<!\\)\|", line)[1]
        for quoted in re.findall(r"`([^`]+)`", cell):
            word = quoted.split()[0].split("/")[0]
            if re.fullmatch(r"[a-z][a-z0-9-]*", word):
                found.add(word)
    return found


def test_every_command_is_documented() -> None:
    missing = registered_commands() - documented_commands() - EXEMPT
    assert not missing, (
        f"these commands ship and are not in docs/cli-reference.md: {sorted(missing)}. "
        "An undocumented command is one nobody finds."
    )


def test_the_reference_names_no_command_that_does_not_exist() -> None:
    """A phantom row is worse than a missing one: the reader gets an error."""
    phantom = documented_commands() - registered_commands()
    assert not phantom, (
        f"docs/cli-reference.md documents commands the CLI does not register: {sorted(phantom)}"
    )


def test_the_parser_actually_exposes_commands() -> None:
    """Guards the guard: an empty set on both sides would pass both tests above."""
    assert len(registered_commands()) > 20
    assert len(documented_commands()) > 20
