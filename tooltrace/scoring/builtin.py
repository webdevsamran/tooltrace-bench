"""Built-in deterministic scorers.

All scorers have signature ``(params, workspace) -> ScorerOutcome`` and are
registered in ``scorer_registry`` by assertion type name.
"""

from __future__ import annotations

import ast
import csv
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema

from tooltrace.scoring.base import ScorerOutcome, register_scorer


def _resolve(workspace: Path, rel: object) -> Path:
    if not isinstance(rel, str):
        raise ValueError("path parameter must be a string")
    return (workspace / rel).resolve()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@register_scorer("file_exists")
def _file_exists(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    ok = path.is_file()
    return ScorerOutcome(1.0 if ok else 0.0, f"{params.get('path')} exists={ok}")


@register_scorer("file_not_exists")
def _file_not_exists(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    ok = not path.exists()
    return ScorerOutcome(1.0 if ok else 0.0, f"{params.get('path')} absent={ok}")


@register_scorer("file_contains")
def _file_contains(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    if not path.is_file():
        return ScorerOutcome(0.0, "file missing")
    text = _read(path)
    raw = params.get("any_of")
    needles = [str(n) for n in raw] if isinstance(raw, list) else [str(params.get("text", ""))]
    hits = [n for n in needles if n in text]
    score = 1.0 if hits else 0.0
    return ScorerOutcome(score, f"matched {len(hits)}/{len(needles)} patterns")


@register_scorer("file_not_contains")
def _file_not_contains(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    if not path.is_file():
        return ScorerOutcome(0.0, "file missing")
    text = _read(path)
    raw = params.get("none_of")
    forbidden = [str(n) for n in raw] if isinstance(raw, list) else [str(params.get("text", ""))]
    bad = [n for n in forbidden if n in text]
    return ScorerOutcome(
        1.0 if not bad else 0.0,
        "clean" if not bad else f"forbidden content present: {bad[:2]}",
    )


@register_scorer("json_schema")
def _json_schema(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    schema = params.get("schema")
    if not path.is_file() or not isinstance(schema, dict):
        return ScorerOutcome(0.0, "file missing or schema invalid")
    try:
        instance = json.loads(_read(path))
        jsonschema.validate(instance, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
        return ScorerOutcome(0.0, f"schema validation failed: {str(exc)[:200]}")
    return ScorerOutcome(1.0, "schema valid")


@register_scorer("json_equals")
def _json_equals(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    expected = params.get("expected")
    if not path.is_file():
        return ScorerOutcome(0.0, "file missing")
    try:
        actual = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        return ScorerOutcome(0.0, f"invalid JSON: {exc}")
    ok = actual == expected
    return ScorerOutcome(1.0 if ok else 0.0, "JSON equal" if ok else "JSON differs")


@register_scorer("csv_equals")
def _csv_equals(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    expected_csv = params.get("expected_csv")
    if not path.is_file() or not isinstance(expected_csv, str):
        return ScorerOutcome(0.0, "file missing or expected_csv invalid")

    def rows(text: str) -> list[list[str]]:
        return list(csv.reader(io.StringIO(text)))

    try:
        equal = rows(_read(path)) == rows(expected_csv)
    except csv.Error as exc:
        return ScorerOutcome(0.0, f"csv parse error: {exc}")
    return ScorerOutcome(1.0 if equal else 0.0, "CSV equal" if equal else "CSV differs")


@register_scorer("command_exit")
def _command_exit(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    command = params.get("command")
    expect = int(params.get("expect_code", 0))  # type: ignore[call-overload]
    if not isinstance(command, str):
        return ScorerOutcome(0.0, "command must be a string")
    timeout = float(params.get("timeout_seconds", 30))  # type: ignore[arg-type]
    import os

    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE", "COVERAGE", "PYTEST_"))
    }
    try:
        proc = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            timeout=timeout,
            shell=True,
            text=True,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ScorerOutcome(0.0, "command timed out")
    ok = proc.returncode == expect
    detail = f"exit={proc.returncode} expected={expect}"
    if not ok and proc.stderr:
        detail += f": {proc.stderr.strip()[:200]}"
    return ScorerOutcome(1.0 if ok else 0.0, detail)


@register_scorer("tests_pass")
def _tests_pass(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    target = str(params.get("path", "."))
    min_ratio = float(params.get("min_ratio", 1.0))  # type: ignore[arg-type]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        target,
    ]
    import os

    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE", "COVERAGE", "PYTEST_"))
    }
    try:
        proc = subprocess.run(
            cmd, cwd=str(workspace), capture_output=True, timeout=120, text=True, env=env
        )
    except subprocess.TimeoutExpired:
        return ScorerOutcome(0.0, "test run timed out")
    output = proc.stdout + proc.stderr

    def count(pattern: str) -> int:
        m = re.search(pattern, output)
        return int(m.group(1)) if m else 0

    passed, failed, errors = (
        count(r"(\d+) passed"),
        count(r"(\d+) failed"),
        count(r"(\d+) error"),
    )
    total = passed + failed + errors
    ratio = passed / total if total else 0.0
    score = 1.0 if ratio >= min_ratio and errors == 0 else round(ratio, 4)
    return ScorerOutcome(
        score,
        f"passed={passed} failed={failed} errors={errors} ratio={ratio:.2f}",
    )


@register_scorer("git_diff")
def _git_diff(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    """Check constraints on `git diff` output inside a git-initialized workspace."""
    raw_contains = params.get("contains")
    contains = [str(c) for c in raw_contains] if isinstance(raw_contains, list) else []
    raw_not = params.get("not_contains")
    not_contains = [str(c) for c in raw_not] if isinstance(raw_not, list) else []
    max_changed = params.get("max_changed_files")
    try:
        proc = subprocess.run(
            ["git", "--no-pager", "diff", "HEAD"],
            cwd=str(workspace),
            capture_output=True,
            timeout=30,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ScorerOutcome(0.0, f"git diff failed: {exc}")
    diff_text = proc.stdout
    problems: list[str] = []
    for needle in contains:
        if needle not in diff_text:
            problems.append(f"diff missing {needle!r}")
    for needle in not_contains:
        if needle in diff_text:
            problems.append(f"diff contains forbidden {needle!r}")
    if max_changed is not None:
        changed = {line.split()[2] for line in diff_text.splitlines() if line.startswith("+++ b/")}
        limit = int(max_changed) if isinstance(max_changed, (int, float)) else 10**9
        if len(changed) > limit:
            problems.append(f"changed files {len(changed)} > {max_changed}")
    return ScorerOutcome(
        1.0 if not problems else 0.0,
        "git constraints satisfied" if not problems else "; ".join(problems),
    )


@register_scorer("ast_check")
def _ast_check(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    path = _resolve(workspace, params.get("path"))
    if not path.is_file():
        return ScorerOutcome(0.0, "file missing")
    source = _read(path)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ScorerOutcome(0.0, f"syntax error: {exc}")
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    raw_defines = params.get("defines")
    must_define = {str(d) for d in raw_defines} if isinstance(raw_defines, list) else set()
    raw_not_defines = params.get("not_defines")
    must_not = {str(d) for d in raw_not_defines} if isinstance(raw_not_defines, list) else set()
    problems = [f"missing definition {d}" for d in sorted(must_define - defined)]
    problems += [f"forbidden definition {d}" for d in sorted(must_not & defined)]
    return ScorerOutcome(
        1.0 if not problems else 0.0,
        "AST constraints satisfied" if not problems else "; ".join(problems),
    )


@register_scorer("data_equals")
def _data_equals(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    """Whitespace-normalized content equality against inline expected text."""
    path = _resolve(workspace, params.get("path"))
    expected = params.get("expected")
    if not path.is_file() or not isinstance(expected, str):
        return ScorerOutcome(0.0, "file missing or expected invalid")
    normalize = lambda s: chr(10).join(line.rstrip() for line in s.strip().splitlines())  # noqa: E731
    ok = normalize(_read(path)) == normalize(expected)
    return ScorerOutcome(1.0 if ok else 0.0, "content equal" if ok else "content differs")


@register_scorer("api_state")
def _api_state(params: dict[str, object], workspace: Path) -> ScorerOutcome:
    """Check a JSON-path value in an API state file written by a mock server."""
    path = _resolve(workspace, params.get("file", "state.json"))
    json_path = str(params.get("json_path", ""))
    expected: Any = params.get("equals")
    if not path.is_file():
        return ScorerOutcome(0.0, "state file missing")
    try:
        doc: Any = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        return ScorerOutcome(0.0, f"invalid state JSON: {exc}")
    current: Any = doc
    for token in [t for t in json_path.split(".") if t]:
        if isinstance(current, list) and token.isdigit():
            idx = int(token)
            current = current[idx] if idx < len(current) else None
        elif isinstance(current, dict):
            current = current.get(token)
        else:
            current = None
            break
    ok = current == expected
    return ScorerOutcome(
        1.0 if ok else 0.0,
        f"{json_path}={'match' if ok else 'mismatch'}",
    )
