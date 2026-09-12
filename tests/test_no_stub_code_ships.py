"""Nothing in the shipped package may be a stub.

This project is installed by individuals and self-hosted by organisations, and
both read the same source. A function that exists, type-checks, has a docstring
and does nothing is worse than an absent one: an absent function fails at the
import, and an empty one returns `None` into whatever called it.

Three things are checked, and the interesting part of each is what it *allows*:

- **empty bodies**, allowing `@abstractmethod` (the empty body is the contract),
  `typing.Protocol` members (structural typing, same reason), and a named
  allowlist of overrides whose whole purpose is to do nothing — silencing
  `BaseHTTPRequestHandler.log_message` is an implementation, not an omission;
- **`NotImplementedError`**, with no allowance at all. Raising it is how a stub
  announces itself;
- **unfinished-work markers** in `tooltrace/` and `scripts/`. `TODO` is
  *semantic* in this project — `promote-trace` writes one into every generated
  draft task, deliberately, so a generated task cannot be mistaken for a
  finished one — so the check is scoped to code that ships behaviour and the
  string is matched as a marker rather than as a word.

The allowlist is the point. A test that simply banned empty bodies would be
turned off the first time somebody wrote a `Protocol`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tooltrace"
SCRIPTS = ROOT / "scripts"

#: `module::function` entries whose empty body *is* the implementation.
#: Each needs a reason, and `test_every_allowance_is_still_needed` deletes the
#: entry from under you when it stops being true.
EMPTY_BODY_ALLOWED = {
    "agents/mcp_http_fixture.py::log_message": "silences per-request stderr logging in a fixture",
    "server/core.py::log_message": "silences per-request stderr logging in the API server",
}

#: Matched as a marker -- `# TODO:`, `TODO(name)` -- not as the word. The word
#: appears legitimately in this package: a generated draft task carries one so
#: that nobody mistakes it for a finished task.
UNFINISHED = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b|\b(FIXME|XXX)\b")


def python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def body_does_nothing(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the body is only a docstring, `pass`, or `...`."""
    statements = list(node.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if not statements:
        return True
    return all(
        isinstance(s, ast.Pass)
        or (
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Constant)
            and s.value.value is Ellipsis
        )
        for s in statements
    )


def is_abstract(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(ast.unparse(d).endswith("abstractmethod") for d in node.decorator_list)


def protocol_classes(tree: ast.Module) -> set[int]:
    """Line numbers of every `class X(Protocol)` body member.

    A `Protocol` is a structural type: its members describe a shape somebody
    else implements, so an empty body is the whole point.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any("Protocol" in ast.unparse(base) for base in node.bases):
            continue
        for member in ast.walk(node):
            if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                lines.add(member.lineno)
    return lines


def empty_bodies(root: Path) -> list[tuple[str, str, int]]:
    """(relative path, function name, line) for every body that does nothing."""
    found: list[tuple[str, str, int]] = []
    for path in python_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        structural = protocol_classes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not body_does_nothing(node):
                continue
            if is_abstract(node) or node.lineno in structural:
                continue
            found.append((path.relative_to(ROOT.parent).as_posix(), node.name, node.lineno))
    return found


PACKAGE_EMPTY = empty_bodies(PACKAGE)


def test_there_is_a_package_to_scan() -> None:
    """An empty walk would make every test below pass vacuously."""
    assert len(python_files(PACKAGE)) >= 50, len(python_files(PACKAGE))


def test_no_function_in_the_package_does_nothing() -> None:
    """Abstract methods and Protocol members are excluded above; what is left
    is a function somebody meant to finish."""
    offenders = [
        f"{path}::{name} (line {line})"
        for path, name, line in PACKAGE_EMPTY
        if f"{path.split('tooltrace/', 1)[-1]}::{name}" not in EMPTY_BODY_ALLOWED
    ]
    assert offenders == [], (
        f"these do nothing and are not abstract, a Protocol member, or allowlisted: {offenders}"
    )


def test_every_allowance_is_still_needed() -> None:
    """An allowlist nobody prunes is how the next stub gets in.

    If one of these grows a real body, or is deleted, the entry has to go --
    otherwise it sits there as pre-approval for a name somebody may reuse.
    """
    present = {f"{path.split('tooltrace/', 1)[-1]}::{name}" for path, name, _ in PACKAGE_EMPTY}
    stale = sorted(set(EMPTY_BODY_ALLOWED) - present)
    assert stale == [], f"these allowances no longer describe anything: {stale}"


def test_every_allowance_gives_a_reason() -> None:
    for key, reason in EMPTY_BODY_ALLOWED.items():
        assert len(reason) > 20, key


@pytest.mark.parametrize("root", [PACKAGE, SCRIPTS], ids=["tooltrace", "scripts"])
def test_nothing_raises_not_implemented(root: Path) -> None:
    """There is no legitimate use of this in shipped code.

    An abstract method's contract is its signature; raising to announce
    incompleteness is a stub saying so out loud.
    """
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in python_files(root)
        if "NotImplementedError" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


@pytest.mark.parametrize("root", [PACKAGE, SCRIPTS], ids=["tooltrace", "scripts"])
def test_no_unfinished_work_markers(root: Path) -> None:
    """Scoped to code that ships behaviour.

    `TODO` is load-bearing vocabulary here: `promote-trace` writes one into
    every section of a generated draft task it cannot derive, precisely so a
    generated task is never mistaken for a finished one. So the marker form is
    matched, and the bare word is not.
    """
    offenders: list[str] = []
    for path in python_files(root):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if UNFINISHED.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    assert offenders == [], offenders


def test_the_marker_pattern_would_actually_catch_one() -> None:
    """A regex that matches nothing makes the test above decorative."""
    assert UNFINISHED.search("    x = 1  # TODO: finish this")
    assert UNFINISHED.search("# FIXME broken")
    # And does not fire on the deliberate vocabulary.
    assert not UNFINISHED.search('    DRAFT_MARKER = "TODO"')
    assert not UNFINISHED.search('        print(f"TODO: {problem}", file=sys.stderr)')


# --- the frontend ------------------------------------------------------------


def test_no_placeholder_copy_ships_in_the_dashboard() -> None:
    """ "Coming soon" in a shipped console is a stub with a marketing voice."""
    web = ROOT / "web" / "src"
    banned = re.compile(r"coming soon|not implemented|under construction|lorem ipsum", re.I)
    offenders = []
    for path in sorted(web.rglob("*.ts*")):
        if "__tests__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if banned.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert offenders == [], offenders
