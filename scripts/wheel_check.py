"""Prove that a *built wheel* is self-contained.

The defect this exists to prevent: the wheel target packaged only ``tooltrace``,
so the JSON Schemas at the repository root never entered the distribution. Every
task load in an installed package raised ``task.schema.json not found`` -- the
whole tool was inert -- and nothing caught it, because the documented quickstart
installs editable from a checkout, where a repo-root ``schemas/`` directory
happens to be two levels up from the loader.

So testing the source tree is not enough, and neither is listing the wheel's
contents. The only honest check builds the wheel, extracts it somewhere the
repository cannot be reached, and runs the exact call that used to fail.

    python scripts/wheel_check.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
EXPECTED_SCHEMAS = ("task", "result", "trace", "bundle-manifest")
MIN_TASK_YAMLS = 19

# Subprocesses must not inherit the parent's coverage/pytest plumbing: mixing
# statement and branch data aborts the pytest session (see AGENTS.md).
_STRIP_PREFIXES = ("COV_CORE", "COVERAGE", "PYTEST_")


def child_env(**overrides: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_STRIP_PREFIXES)}
    env.update(overrides)
    return env


def build_wheel(dest: Path) -> Path:
    """Build a wheel into *dest* and return its path."""
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dest)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    wheels = sorted(dest.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"no wheel produced in {dest}")
    return wheels[-1]


def check_wheel_payload(wheel: Path) -> list[str]:
    """Structural checks: the schemas are present, and byte-identical to source."""
    problems: list[str] = []
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        for name in EXPECTED_SCHEMAS:
            member = f"tooltrace/schema_data/{name}.schema.json"
            if member not in names:
                problems.append(f"wheel is missing {member}")
                continue
            packaged = zf.read(member)
            authored = (SCHEMA_DIR / f"{name}.schema.json").read_bytes()
            if packaged != authored:
                problems.append(f"{member} differs from the authored schemas/{name}.schema.json")
        yamls = sum(1 for n in names if "/tasks/packs/" in n and n.endswith(".yaml"))
        if yamls < MIN_TASK_YAMLS:
            problems.append(f"wheel carries {yamls} task YAMLs, expected at least {MIN_TASK_YAMLS}")
    return problems


_PROBE = """
import json, sys
from pathlib import Path

site = Path(sys.argv[1])
out = {}

import tooltrace
# If an editable install shadowed the extracted copy this check would pass
# vacuously, so prove which tooltrace we actually imported.
out["imported_from_extract"] = Path(tooltrace.__file__).resolve().is_relative_to(site)
out["repo_schemas_absent"] = not (site / "schemas").exists()

from tooltrace.core.schemas import schema_source, load_all_schemas
src = schema_source()
out["schema_source"] = str(src) if src else None
out["source_is_packaged"] = bool(src and src.resolve() == (site / "tooltrace" / "schema_data").resolve())
out["schemas_loaded"] = sorted(load_all_schemas())

from tooltrace.tasks import load_all_tasks
from tooltrace.tasks.loader import validate_task_document
tasks = load_all_tasks()
out["task_count"] = len(tasks)

import yaml
sample = sorted((site / "tooltrace" / "tasks" / "packs").rglob("*.yaml"))[0]
out["validation_errors"] = validate_task_document(yaml.safe_load(sample.read_text(encoding="utf-8")))

print(json.dumps(out))
"""


def check_extracted_wheel_runs(wheel: Path, work: Path) -> list[str]:
    """Extract the wheel away from the repo and run the calls that used to fail."""
    site = work / "site"
    site.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(site)

    problems: list[str] = []
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(site)],
        cwd=work,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(PYTHONPATH=str(site)),
    )
    if proc.returncode != 0:
        return [f"probe failed (exit {proc.returncode}): {(proc.stderr or '').strip()[:600]}"]

    import json

    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [f"probe produced unreadable output: {proc.stdout[:400]!r}"]

    if not out["imported_from_extract"]:
        problems.append("imported tooltrace from outside the extracted wheel; check is vacuous")
    if not out["repo_schemas_absent"]:
        problems.append(
            "a schemas/ directory sits beside the extract, so the repo fallback could fire"
        )
    if not out["source_is_packaged"]:
        problems.append(f"schemas resolved from {out['schema_source']}, not the packaged copy")
    missing = sorted(set(EXPECTED_SCHEMAS) - set(out["schemas_loaded"]))
    if missing:
        problems.append(f"packaged schemas missing: {missing}")
    if out["task_count"] < MIN_TASK_YAMLS:
        problems.append(
            f"loaded {out['task_count']} tasks from the wheel, expected {MIN_TASK_YAMLS}"
        )
    if out["validation_errors"]:
        problems.append(f"a packaged task failed validation: {out['validation_errors'][:3]}")

    cli = subprocess.run(
        [sys.executable, "-m", "tooltrace.cli.main", "tasks", "--json"],
        cwd=work,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(PYTHONPATH=str(site)),
    )
    if cli.returncode != 0:
        problems.append(
            f"`tooltrace tasks --json` exited {cli.returncode}: {(cli.stderr or '').strip()[:300]}"
        )
    return problems


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tooltrace-wheel-") as tmp:
        work = Path(tmp)
        try:
            wheel = build_wheel(work / "dist")
        except subprocess.CalledProcessError as exc:
            print(f"FAIL: wheel build failed\n{(exc.stderr or '')[:800]}", file=sys.stderr)
            return 1
        problems = check_wheel_payload(wheel) + check_extracted_wheel_runs(wheel, work)

    if problems:
        print("FAIL: the built wheel is not self-contained", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"ok: {wheel.name} ships its schemas and loads every task without a checkout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
