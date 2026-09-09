"""The workspace diff is one of the six artifacts in a `.tooltrace` bundle.

It is checksummed into the manifest, rendered by the dashboard, and cited by the
evidence dossier as the record of what a run changed. Which makes it surprising
that `workspace_diff` had no test of its own: the only references to the string
"workspace_diff" in `tests/` were an event *type* in an ingest fixture.

The bug that absence hid: `lines.extend(f"--- /dev/null{chr(10)}+++ {path}")`.
`list.extend` iterates its argument, and iterating a string yields characters,
so every created and every deleted file produced a header spelled one character
per line — thirty-odd lines of single letters where two lines belonged.

It stayed invisible because the three tasks used to generate this repository's
sample bundles all *modify* an existing file, and that path goes through
`difflib.unified_diff`, which returns a list. Run any task that creates a file —
which is most agent work — and the bundle shipped a corrupted artifact.

So the shape of the output is what these tests assert, not just its content.
"""

from __future__ import annotations

from pathlib import Path

from tooltrace.sandbox.diff import changed_paths, snapshot, workspace_diff


def _lines(diff: str) -> list[str]:
    return diff.splitlines()


# --- created files ----------------------------------------------------------


def test_a_created_file_gets_a_two_line_header() -> None:
    diff = workspace_diff({}, {"summary.txt": "hello\n"})
    assert _lines(diff)[:2] == ["--- /dev/null", "+++ summary.txt"]


def test_a_created_file_does_not_spell_its_header_one_character_per_line() -> None:
    """The exact regression: `extend` over a string instead of `append`."""
    diff = workspace_diff({}, {"summary.txt": "hello\n"})
    assert "-\n-\n-" not in diff
    # Every line is either a header or a marked content line; none is a lone
    # character. A single-character line here means the string was iterated.
    for line in _lines(diff):
        assert len(line) != 1 or line in {"+", "-", " "}, f"stray character line: {line!r}"


def test_created_content_is_present_and_marked() -> None:
    diff = workspace_diff({}, {"a.txt": "one\ntwo\n"})
    assert "+one" in _lines(diff)
    assert "+two" in _lines(diff)


# --- deleted files ----------------------------------------------------------


def test_a_deleted_file_gets_a_two_line_header() -> None:
    diff = workspace_diff({"gone.txt": "bye\n"}, {})
    assert _lines(diff)[:2] == ["--- gone.txt", "+++ /dev/null"]


def test_deleted_content_is_present_and_marked() -> None:
    diff = workspace_diff({"gone.txt": "bye\n"}, {})
    assert "-bye" in _lines(diff)


# --- modified files (the path that always worked) ---------------------------


def test_a_modified_file_still_produces_a_unified_diff() -> None:
    diff = workspace_diff({"a.txt": "old\n"}, {"a.txt": "new\n"})
    assert "--- a.txt" in diff and "+++ a.txt" in diff
    assert "-old" in _lines(diff) and "+new" in _lines(diff)


def test_an_unchanged_file_produces_nothing() -> None:
    assert workspace_diff({"a.txt": "same\n"}, {"a.txt": "same\n"}) == ""


# --- several changes at once ------------------------------------------------


def test_creations_deletions_and_edits_stay_separable() -> None:
    """A reader must be able to tell which hunk belongs to which file."""
    diff = workspace_diff(
        {"edited.txt": "old\n", "gone.txt": "x\n"},
        {"edited.txt": "new\n", "made.txt": "y\n"},
    )
    lines = _lines(diff)
    headers = [i for i, line in enumerate(lines) if line.startswith("--- ")]
    assert len(headers) == 3
    # Paths are sorted, so the order is stable across runs -- a diff that
    # reordered itself would make two identical runs look different.
    assert [lines[i] for i in headers] == ["--- edited.txt", "--- gone.txt", "--- /dev/null"]


def test_ordering_is_deterministic() -> None:
    before = {"b.txt": "1\n", "a.txt": "1\n"}
    after = {"b.txt": "2\n", "a.txt": "2\n"}
    assert workspace_diff(before, after) == workspace_diff(dict(before), dict(after))


# --- against a real directory -----------------------------------------------


def test_end_to_end_over_a_real_workspace(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("same\n", encoding="utf-8")
    (tmp_path / "edit.txt").write_text("before\n", encoding="utf-8")
    before = snapshot(tmp_path)

    (tmp_path / "edit.txt").write_text("after\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("fresh\n", encoding="utf-8")
    after = snapshot(tmp_path)

    assert changed_paths(before, after) == ["edit.txt", "new.txt"]
    diff = workspace_diff(before, after)
    assert "--- /dev/null" in diff
    assert "+++ new.txt" in diff
    assert "+fresh" in _lines(diff)
    assert "keep.txt" not in diff
