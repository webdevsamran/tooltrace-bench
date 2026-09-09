"""Locating the JSON Schemas, wherever they happen to live.

The schemas are authored once at the repository root (``schemas/*.json``) and
copied into the wheel at build time by a hatch ``force-include`` directive, so
an installed package carries its own copy at ``tooltrace/schema_data/``.

This module exists because that copy did not used to be made. The wheel target
declared ``packages = ["tooltrace"]`` and nothing else, so ``schemas/`` never
entered the distribution. ``tasks/loader.py`` looked for a repo-root
``schemas/`` directory and, failing that, fell back to
``resources.files("tooltrace") / "schema_data"`` -- a directory that did not
exist either. The fallback branch was annotated ``# pragma: no cover``, so no
test ever executed it. The result was that every ``pip install`` of a built
wheel produced a package where ``validate_task_document`` raised
``TaskValidationError("task.schema.json not found")`` for *every* task: no
``tooltrace tasks``, no ``tooltrace run``, nothing. It stayed invisible because
the documented quickstart installs editable from a checkout, where the repo
copy resolves and the broken branch never runs.

Two consequences shape the design here:

- **Packaged first, repo second.** A wheel must never silently depend on a
  checkout happening to be nearby. If the packaged copy is present it wins, so
  an installed package is exercised the same way a user's would be.
- **No ``pragma: no cover``.** Both roots are ordinary arguments to
  :func:`load_schemas_from`, so each is unit-testable against a temporary
  directory and coverage is honest rather than excluded.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

from tooltrace.core.exceptions import ToolTraceError

SCHEMA_NAMES: tuple[str, ...] = ("task", "result", "trace", "bundle-manifest")

_SUFFIX = ".schema.json"


def packaged_schema_root() -> Path | None:
    """The copy inside the installed package, if the build included one."""
    try:
        root = Path(str(resources.files("tooltrace"))) / "schema_data"
    except (ModuleNotFoundError, TypeError):  # pragma: no cover - defensive
        return None
    return root if root.is_dir() else None


def repo_schema_root() -> Path | None:
    """The authored copy at the repository root, present in a checkout."""
    root = Path(__file__).resolve().parents[2] / "schemas"
    return root if root.is_dir() else None


def schema_roots() -> list[Path]:
    """Candidate roots, most authoritative first."""
    return [root for root in (packaged_schema_root(), repo_schema_root()) if root is not None]


def load_schemas_from(root: Path) -> dict[str, dict[str, object]]:
    """Read every ``*.schema.json`` in *root*, keyed by its bare name."""
    schemas: dict[str, dict[str, object]] = {}
    for path in sorted(root.glob("*" + _SUFFIX)):
        schemas[path.name.removesuffix(_SUFFIX)] = json.loads(path.read_text(encoding="utf-8"))
    return schemas


@lru_cache(maxsize=1)
def load_all_schemas() -> dict[str, dict[str, object]]:
    """Every schema from the first root that yields any."""
    for root in schema_roots():
        schemas = load_schemas_from(root)
        if schemas:
            return schemas
    return {}


def schema_source() -> Path | None:
    """Which root the loaded schemas came from. Reported by ``tooltrace doctor``."""
    for root in schema_roots():
        if load_schemas_from(root):
            return root
    return None


def load_schema(name: str) -> dict[str, object]:
    """One schema by name, or a diagnosable error naming the file we wanted.

    The message is kept byte-identical to the one this failure produced before
    the resolver existed, so ``docs/exit-codes.md`` and the tests that pin the
    exit-code contract keep describing reality.
    """
    schema = load_all_schemas().get(name)
    if schema is None:
        raise ToolTraceError(f"{name}{_SUFFIX} not found")
    return schema
