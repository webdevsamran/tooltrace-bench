"""Where the JSON Schemas come from, and what happens when they are absent.

The resolver replaced a branch annotated ``# pragma: no cover`` -- the branch
that ran on every wheel install, and that nobody had ever executed. Excluding
it from coverage is what let it ship broken. Both roots are therefore ordinary
arguments here, and both are exercised.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tooltrace.core import schemas as schema_mod
from tooltrace.core.exceptions import ToolTraceError

_ROOT = Path(__file__).resolve().parent.parent
_AUTHORED = _ROOT / "schemas"


def test_an_empty_root_yields_no_schemas(tmp_path: Path) -> None:
    assert schema_mod.load_schemas_from(tmp_path) == {}


def test_a_seeded_root_yields_every_schema(tmp_path: Path) -> None:
    for src in _AUTHORED.glob("*.schema.json"):
        shutil.copy(src, tmp_path / src.name)
    loaded = schema_mod.load_schemas_from(tmp_path)
    assert sorted(loaded) == sorted(schema_mod.SCHEMA_NAMES)
    assert all(isinstance(v, dict) for v in loaded.values())


def test_the_packaged_root_wins_over_the_repo_root(tmp_path: Path, monkeypatch) -> None:
    """A wheel must never silently fall back to a checkout that happens to be near."""
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    (packaged / "task.schema.json").write_text(
        json.dumps({"$id": "packaged-marker", "type": "object"}), encoding="utf-8"
    )
    monkeypatch.setattr(schema_mod, "packaged_schema_root", lambda: packaged)
    monkeypatch.setattr(schema_mod, "repo_schema_root", lambda: _AUTHORED)
    schema_mod.load_all_schemas.cache_clear()
    try:
        assert schema_mod.load_all_schemas()["task"]["$id"] == "packaged-marker"
        assert schema_mod.schema_source() == packaged
    finally:
        schema_mod.load_all_schemas.cache_clear()


def test_a_missing_schema_names_the_file_it_wanted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(schema_mod, "packaged_schema_root", lambda: None)
    monkeypatch.setattr(schema_mod, "repo_schema_root", lambda: tmp_path)
    schema_mod.load_all_schemas.cache_clear()
    try:
        with pytest.raises(ToolTraceError, match=r"task\.schema\.json not found"):
            schema_mod.load_schema("task")
    finally:
        schema_mod.load_all_schemas.cache_clear()


def test_the_repo_checkout_resolves_every_declared_schema() -> None:
    schema_mod.load_all_schemas.cache_clear()
    loaded = schema_mod.load_all_schemas()
    assert sorted(loaded) == sorted(schema_mod.SCHEMA_NAMES)
    assert schema_mod.schema_source() is not None


def test_the_loader_reads_through_the_resolver() -> None:
    from tooltrace.tasks.loader import _schemas

    assert sorted(_schemas()) == sorted(schema_mod.SCHEMA_NAMES)
