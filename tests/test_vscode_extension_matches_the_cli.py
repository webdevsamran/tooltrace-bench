"""The VS Code extension is a second copy of this CLI's interface. Check it.

An editor extension that shells out to a command line holds an unchecked
restatement of that command line's flags, and this project has already shipped
exactly that failure in prose: the 0.3.0 quickstart named a `--pack` flag the
CLI never had, found by hand, after release, by somebody trying to follow it.
`tests/test_documented_commands_parse.py` closed that hole for the
documentation. This closes it for the extension.

Every entry in `extensions/vscode/lib/cli.js`'s `INVOCATIONS` table is fed to
the real argument parser -- the one that will reject it when a user clicks the
button. A subcommand that is renamed or a flag that is dropped fails here, in
the Python suite, rather than in somebody's editor.

The table is parsed out of the JavaScript rather than duplicated in Python.
A second copy of the list would need its own test.

The extension's own behaviour is tested in `extensions/vscode/test/cli.test.js`
under `node --test`, with no dependencies to install; `test_the_node_tests_pass`
below runs it when node is available and says plainly when it is not.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tooltrace.cli.main import build_parser

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extensions" / "vscode"
CLI_JS = EXTENSION / "lib" / "cli.js"
MANIFEST = EXTENSION / "package.json"

#: One `name: { args: [...] }` entry in the INVOCATIONS object.
ENTRY = re.compile(r"(\w+):\s*\{\s*args:\s*\[([^\]]*)\]\s*\}")
#: A placeholder the extension substitutes at call time.
PLACEHOLDER = re.compile(r"^\{(\w+)\}$")


def invocations() -> dict[str, list[str]]:
    source = CLI_JS.read_text(encoding="utf-8")
    start = source.index("const INVOCATIONS")
    end = source.index("class MissingParameter")
    found = {}
    for name, raw in ENTRY.findall(source[start:end]):
        found[name] = [token.strip().strip("'\"") for token in raw.split(",") if token.strip()]
    return found


INVOCATIONS = invocations()


def test_the_table_was_actually_found() -> None:
    """A regex that matched nothing would make every test below vacuous."""
    assert len(INVOCATIONS) >= 5, INVOCATIONS


@pytest.mark.parametrize("name", sorted(INVOCATIONS))
def test_the_subcommand_exists(name: str) -> None:
    import argparse

    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    assert INVOCATIONS[name][0] in set(subparsers[0].choices)


@pytest.mark.parametrize("name", sorted(INVOCATIONS))
def test_every_flag_exists_on_that_subcommand(name: str) -> None:
    """Parsed against the subcommand's own parser, not string-matched."""
    import argparse

    args = INVOCATIONS[name]
    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    subparser = subparsers[0].choices[args[0]]
    known = {option for action in subparser._actions for option in action.option_strings}
    for token in args[1:]:
        if token.startswith("--"):
            assert token in known, f"{name}: `{token}` is not an option of `{args[0]}`"


@pytest.mark.parametrize("name", sorted(INVOCATIONS))
def test_the_command_parses_with_the_placeholders_filled_in(name: str) -> None:
    """The flags *and* the shape: a positional that moved fails here too."""
    filled = ["placeholder" if PLACEHOLDER.match(token) else token for token in INVOCATIONS[name]]
    parser = build_parser()
    try:
        parser.parse_args(filled)
    except SystemExit as exit_code:  # pragma: no cover - only on a real break
        if exit_code.code not in (0, None):
            pytest.fail(f"{name}: `tooltrace {' '.join(filled)}` does not parse")


@pytest.mark.parametrize("name", sorted(INVOCATIONS))
def test_every_invocation_asks_for_json(name: str) -> None:
    """The extension parses stdout. A command not asked for JSON returns prose."""
    assert "--json" in INVOCATIONS[name], name


def test_every_contributed_command_is_registered_by_the_extension() -> None:
    """A menu entry with no handler is a button that does nothing."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contributed = {c["command"] for c in manifest["contributes"]["commands"]}
    source = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    registered = set(re.findall(r"registerCommand\(\s*'([^']+)'", source))
    assert contributed == registered, (
        f"contributed but not registered: {sorted(contributed - registered)}; "
        f"registered but not contributed: {sorted(registered - contributed)}"
    )


def test_the_extension_entry_point_exists() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert (EXTENSION / manifest["main"]).resolve().is_file()


def test_the_extension_does_not_vendor_a_copy_of_this_package() -> None:
    """It shells out to whatever `tooltrace` is on PATH.

    A bundled copy would drift from the installed one, and the two would
    disagree about results while looking identical.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert not manifest.get("dependencies"), manifest.get("dependencies")
    assert not (EXTENSION / "node_modules").exists()


def test_the_extension_ships_no_build_step() -> None:
    """No bundler, no transpile, no lockfile to go stale.

    VS Code loads CommonJS directly, so the shipped files are the source files.
    Anything else would put a build artifact in the repository that nothing here
    regenerates.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "build" not in manifest.get("scripts", {})
    assert not list(EXTENSION.glob("*.ts"))


def test_the_node_tests_pass() -> None:
    """Run the extension's own suite, or say why it did not run.

    Skipped rather than silently passing when node is absent: a green test that
    executed nothing is worse than a skip that says so.
    """
    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the machine
        pytest.skip("node is not on PATH; extensions/vscode/test was not run")
    proc = subprocess.run(
        [node, "--test", "test/cli.test.js"],
        cwd=EXTENSION,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "# fail 0" in proc.stdout or "fail 0" in proc.stdout
