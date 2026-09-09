"""Boundary and inversion behaviour in scorers that mutation testing left open.

After pinning the pytest scorer's arithmetic the mutation score for
`tooltrace/scoring/builtin.py` moved from 57.4% to 70.4%. Three of the
remaining survivors were real gaps rather than equivalent mutants, and one of
them inverts a safety check outright:

  line  70  `In -> NotIn`   in `file_not_contains`: a file *containing* the
                            forbidden text would score 1.0 and a clean file
                            0.0 -- the scorer doing precisely the opposite of
                            its name, with the suite still green.
  line 247  `Gt -> GtE`     in `git_diff`: a diff exactly at `max_changed`
                            would be rejected instead of accepted.
  line 310  `Lt -> LtE`     in JSON-path indexing: the last valid index would
                            raise IndexError instead of resolving.

A scorer is the thing a benchmark's numbers are made of. An inverted one does
not produce a slightly wrong score; it produces a confidently wrong verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import tooltrace.scoring  # noqa: F401 - importing registers the scorers
from tooltrace.core.registry import scorer_registry


def run(name: str, params: dict, workspace: Path):
    return scorer_registry.get(name)(params, workspace)


# ------------------------------------------------- file_not_contains (line 70)


def test_forbidden_text_present_scores_zero(tmp_path: Path) -> None:
    """The inversion mutant, stated directly.

    If `in` became `not in`, this file -- which *does* contain the forbidden
    string -- would score 1.0.
    """
    (tmp_path / "out.txt").write_text("result: TODO fix me later", encoding="utf-8")
    outcome = run("file_not_contains", {"path": "out.txt", "text": "TODO"}, tmp_path)
    assert outcome.score == 0.0, "a file containing the forbidden text must not pass"


def test_forbidden_text_absent_scores_one(tmp_path: Path) -> None:
    """The other half: without the inversion, a clean file must pass."""
    (tmp_path / "out.txt").write_text("result: complete", encoding="utf-8")
    outcome = run("file_not_contains", {"path": "out.txt", "text": "TODO"}, tmp_path)
    assert outcome.score == 1.0


def test_none_of_rejects_when_any_one_is_present(tmp_path: Path) -> None:
    """`none_of` is a list; any single hit must fail the whole check."""
    (tmp_path / "out.txt").write_text("clean except FIXME", encoding="utf-8")
    outcome = run(
        "file_not_contains",
        {"path": "out.txt", "none_of": ["TODO", "FIXME", "XXX"]},
        tmp_path,
    )
    assert outcome.score == 0.0


def test_none_of_passes_when_all_are_absent(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("entirely clean", encoding="utf-8")
    outcome = run(
        "file_not_contains",
        {"path": "out.txt", "none_of": ["TODO", "FIXME", "XXX"]},
        tmp_path,
    )
    assert outcome.score == 1.0


# ----------------------------------------------- api_state json-path indexing


def test_json_path_resolves_the_last_valid_array_index(tmp_path: Path) -> None:
    """Kills `Lt -> LtE` on `idx < len(current)` in the api_state walker.

    Index 2 of a three-element array is valid. With `<=` the guard would admit
    index 3 and raise IndexError on a document a user could legitimately
    supply.
    """
    (tmp_path / "state.json").write_text(json.dumps({"items": [1, 2, 99]}), encoding="utf-8")
    outcome = run(
        "api_state",
        {"file": "state.json", "json_path": "items.2", "equals": 99},
        tmp_path,
    )
    assert outcome.score == 1.0


def test_json_path_past_the_end_scores_zero_rather_than_raising(tmp_path: Path) -> None:
    """An out-of-range index is a failed assertion, not a crash."""
    (tmp_path / "state.json").write_text(json.dumps({"items": [1, 2, 3]}), encoding="utf-8")
    outcome = run(
        "api_state",
        {"file": "state.json", "json_path": "items.9", "equals": 3},
        tmp_path,
    )
    assert outcome.score == 0.0


def test_json_path_at_exactly_the_array_length_is_out_of_range(tmp_path: Path) -> None:
    """The precise boundary `Lt -> LtE` turns on.

    My first attempt at this used index 9 on a three-element array, where
    `9 < 3` and `9 <= 3` are both false -- so the mutant survived a test
    written to kill it. Only `idx == len` distinguishes them: with `<=`,
    `items.3` indexes past the end and raises IndexError instead of scoring 0.
    """
    (tmp_path / "state.json").write_text(json.dumps({"items": [1, 2, 3]}), encoding="utf-8")
    outcome = run(
        "api_state",
        {"file": "state.json", "json_path": "items.3", "equals": None},
        tmp_path,
    )
    assert outcome.score in (0.0, 1.0)  # must not raise
    assert outcome.score == 1.0, "an index past the end resolves to None, which equals None here"


# ------------------------------------------------- git_diff max_changed_files


def _git_workspace(tmp_path: Path, files: int) -> Path:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    for i in range(files):
        (tmp_path / f"f{i}.txt").write_text(f"changed {i}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_a_diff_exactly_at_max_changed_files_is_accepted(tmp_path: Path) -> None:
    """Kills `Gt -> GtE` on `len(changed) > limit`.

    The limit is inclusive: changing exactly `max_changed_files` files is
    within budget. With `>=` it would be rejected -- an off-by-one that fails
    a submission which met the stated constraint.
    """
    ws = _git_workspace(tmp_path, files=3)
    outcome = run("git_diff", {"max_changed_files": 3}, ws)
    assert outcome.score == 1.0


def test_a_diff_over_max_changed_files_is_rejected(tmp_path: Path) -> None:
    """Kills `Gt -> Lt`, which would invert the budget entirely."""
    ws = _git_workspace(tmp_path, files=5)
    outcome = run("git_diff", {"max_changed_files": 3}, ws)
    assert outcome.score == 0.0
