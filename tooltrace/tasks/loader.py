"""Task loading and formal validation.

Tasks are YAML (or JSON) documents validated against
``schemas/task.schema.json`` before being parsed into a
:class:`TaskDefinition`. Pack discovery order:

1. built-in packs shipped in ``tooltrace/tasks/packs/``
2. directories registered under the ``tooltrace.task_packs`` entry point
3. explicit extra directories supplied by callers
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import jsonschema
import yaml

from tooltrace.core.exceptions import TaskValidationError
from tooltrace.core.models import TaskDefinition
from tooltrace.core.registry import discover_plugins

_SCHEMA_CACHE: dict[str, dict[str, object]] | None = None


def _schemas() -> dict[str, dict[str, object]]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        cache: dict[str, dict[str, object]] = {}
        schema_root = resources.files("tooltrace") / "schema_data"
        # schemas live at repo root; fall back to packaged copies
        repo_schema_dir = Path(__file__).resolve().parents[2] / "schemas"
        source = repo_schema_dir if repo_schema_dir.is_dir() else None
        if source is not None:
            for f in sorted(source.glob("*.json")):
                name = f.name.removesuffix(".schema.json")
                cache[name] = json.loads(f.read_text(encoding="utf-8"))
        else:  # pragma: no cover - wheel installs without repo checkout
            for f in sorted(schema_root.glob("*.json")):
                name = f.name.removesuffix(".schema.json")
                cache[name] = json.loads(f.read_text(encoding="utf-8"))
        _SCHEMA_CACHE = cache
    return _SCHEMA_CACHE


def validate_task_document(doc: object) -> list[str]:
    """Validate a raw task document against the JSON Schema; return errors."""
    schema = _schemas().get("task")
    if schema is None:
        raise TaskValidationError("task.schema.json not found")
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in sorted(validator.iter_errors(doc), key=str)]


def parse_task_document(doc: object, source: str = "<memory>") -> TaskDefinition:
    """Validate then parse one task document."""
    errors = validate_task_document(doc)
    if errors:
        raise TaskValidationError(
            f"{source}: task failed schema validation: " + "; ".join(errors[:5])
        )
    try:
        return TaskDefinition.model_validate(doc)
    except Exception as exc:
        raise TaskValidationError(f"{source}: semantic validation failed: {exc}") from exc


def load_task_file(path: Path) -> TaskDefinition:
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text) if path.suffix in {".yaml", ".yml"} else json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise TaskValidationError(f"{path}: parse error: {exc}") from exc
    return parse_task_document(doc, str(path))


def builtin_pack_dirs() -> list[Path]:
    packs_root = Path(__file__).resolve().parent / "packs"
    if not packs_root.is_dir():
        return []
    return sorted(d for d in packs_root.iterdir() if d.is_dir())


def plugin_pack_dirs() -> list[Path]:
    dirs: list[Path] = []
    for _name, obj in discover_plugins("tooltrace.task_packs").items():
        path = Path(str(obj)) if not isinstance(obj, Path) else obj
        if path.is_dir():
            dirs.append(path)
        elif isinstance(obj, type):  # plugin may expose a class attr
            candidate = getattr(obj, "pack_dir", None)
            if candidate and Path(str(candidate)).is_dir():
                dirs.append(Path(str(candidate)))
    return dirs


def all_pack_dirs(extra: list[Path] | None = None) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for d in [*builtin_pack_dirs(), *plugin_pack_dirs(), *(extra or [])]:
        rp = d.resolve()
        if rp not in seen:
            seen.add(rp)
            ordered.append(d)
    return ordered


def load_pack(pack_dir: Path) -> list[TaskDefinition]:
    tasks: list[TaskDefinition] = []
    for f in sorted(list(pack_dir.glob("*.yaml")) + list(pack_dir.glob("*.yml"))):
        tasks.append(load_task_file(f))
    return tasks


def load_all_tasks(extra_dirs: list[Path] | None = None) -> list[TaskDefinition]:
    tasks: list[TaskDefinition] = []
    for d in all_pack_dirs(extra_dirs):
        tasks.extend(load_pack(d))
    return tasks


def find_task(task_id: str, extra_dirs: list[Path] | None = None) -> TaskDefinition:
    for task in load_all_tasks(extra_dirs):
        if task.id == task_id:
            return task
    raise TaskValidationError(
        f"task '{task_id}' not found; run `tooltrace tasks` to list available tasks"
    )
