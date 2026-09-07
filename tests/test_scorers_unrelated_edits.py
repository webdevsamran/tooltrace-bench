"""Two deterministic scorers that catch subtle agent misbehaviour (#11).

`ast_unrelated_edits` catches an agent that fixes the requested thing and also
quietly rewrites something else -- which a file-level `unnecessary_changes`
count cannot see, because only one file was touched, as expected.

`json_set_equals` stops penalising a correct answer whose collection happens
to be in a different order, when the task never specified one.
"""

from __future__ import annotations

import json
from pathlib import Path

from tooltrace.scoring.builtin import _ast_unrelated_edits, _json_set_equals

_BEFORE = '''\
def add(a, b):
    """Add two numbers."""
    return a + b


def subtract(a, b):
    return a - b


class Helper:
    def run(self):
        return 1
'''


def _workspace(tmp_path: Path, after: str, before: str = _BEFORE) -> Path:
    (tmp_path / ".before").mkdir(exist_ok=True)
    (tmp_path / ".before" / "m.py").write_text(before, encoding="utf-8")
    (tmp_path / "m.py").write_text(after, encoding="utf-8")
    return tmp_path


def _score(tmp_path: Path, **extra: object):
    params: dict[str, object] = {"path": "m.py", "reference": ".before/m.py", **extra}
    return _ast_unrelated_edits(params, tmp_path)


def test_fixing_only_the_allowed_definition_scores_one(tmp_path: Path) -> None:
    after = _BEFORE.replace("return a - b", "return b - a")
    ws = _workspace(tmp_path, after)
    outcome = _score(ws, allow=["subtract"])
    assert outcome.score == 1.0, outcome.detail


def test_touching_an_unrelated_definition_scores_zero(tmp_path: Path) -> None:
    """The whole point: the requested fix landed, but so did a stray edit."""
    after = _BEFORE.replace("return a - b", "return b - a").replace(
        "return a + b", "return a + b + 0"
    )
    ws = _workspace(tmp_path, after)
    outcome = _score(ws, allow=["subtract"])
    assert outcome.score == 0.0
    assert "add" in outcome.detail


def test_reformatting_is_not_treated_as_a_change(tmp_path: Path) -> None:
    """Comments and indentation must not count; behaviour is what matters."""
    after = _BEFORE.replace('"""Add two numbers."""', '"""Add two numbers together."""')
    after = after.replace("def subtract(a, b):", "def subtract(a, b):  # noqa")
    ws = _workspace(tmp_path, after)
    assert _score(ws).score == 1.0


def test_deleting_a_definition_is_reported(tmp_path: Path) -> None:
    after = _BEFORE.split("class Helper")[0]
    ws = _workspace(tmp_path, after)
    outcome = _score(ws)
    assert outcome.score == 0.0
    assert "Helper" in outcome.detail


def test_adding_an_unrequested_definition_is_reported(tmp_path: Path) -> None:
    after = _BEFORE + "\n\ndef sneaky():\n    return 99\n"
    ws = _workspace(tmp_path, after)
    outcome = _score(ws)
    assert outcome.score == 0.0
    assert "sneaky" in outcome.detail


def test_missing_reference_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(_BEFORE, encoding="utf-8")
    outcome = _ast_unrelated_edits({"path": "m.py", "reference": "nope.py"}, tmp_path)
    assert outcome.score == 0.0
    assert "reference" in outcome.detail


def test_syntax_error_fails_closed(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, "def broken(:\n")
    outcome = _score(ws)
    assert outcome.score == 0.0
    assert "syntax error" in outcome.detail


# --------------------------------------------------------------- set equality


def _write_json(tmp_path: Path, payload: object) -> Path:
    (tmp_path / "out.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_order_does_not_matter(tmp_path: Path) -> None:
    ws = _write_json(tmp_path, [{"id": 2}, {"id": 1}])
    outcome = _json_set_equals({"path": "out.json", "expected": [{"id": 1}, {"id": 2}]}, ws)
    assert outcome.score == 1.0, outcome.detail


def test_key_order_within_members_does_not_matter(tmp_path: Path) -> None:
    ws = _write_json(tmp_path, [{"b": 2, "a": 1}])
    outcome = _json_set_equals({"path": "out.json", "expected": [{"a": 1, "b": 2}]}, ws)
    assert outcome.score == 1.0, outcome.detail


def test_a_missing_member_still_fails(tmp_path: Path) -> None:
    ws = _write_json(tmp_path, [{"id": 1}])
    outcome = _json_set_equals({"path": "out.json", "expected": [{"id": 1}, {"id": 2}]}, ws)
    assert outcome.score == 0.0
    assert "missing" in outcome.detail


def test_duplicates_are_counted_not_collapsed(tmp_path: Path) -> None:
    """A real set would call [1, 1] and [1] equal. That would hide a bug."""
    ws = _write_json(tmp_path, [1, 1])
    outcome = _json_set_equals({"path": "out.json", "expected": [1]}, ws)
    assert outcome.score == 0.0


def test_pointer_selects_a_nested_collection(tmp_path: Path) -> None:
    ws = _write_json(tmp_path, {"result": {"items": ["b", "a"]}})
    outcome = _json_set_equals(
        {"path": "out.json", "expected": ["a", "b"], "pointer": "result.items"}, ws
    )
    assert outcome.score == 1.0, outcome.detail


def test_bad_pointer_reports_where_it_failed(tmp_path: Path) -> None:
    ws = _write_json(tmp_path, {"result": {}})
    outcome = _json_set_equals({"path": "out.json", "expected": [], "pointer": "result.items"}, ws)
    assert outcome.score == 0.0
    assert "items" in outcome.detail


def test_non_list_target_is_reported_clearly(tmp_path: Path) -> None:
    ws = _write_json(tmp_path, {"a": 1})
    outcome = _json_set_equals({"path": "out.json", "expected": []}, ws)
    assert outcome.score == 0.0
    assert "not a list" in outcome.detail


def test_invalid_json_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "out.json").write_text("{not json", encoding="utf-8")
    outcome = _json_set_equals({"path": "out.json", "expected": []}, tmp_path)
    assert outcome.score == 0.0
    assert "invalid JSON" in outcome.detail
