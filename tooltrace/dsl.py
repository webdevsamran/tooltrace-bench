"""Python assertion-builder DSL for task authors.

A thin, typed layer over :class:`tooltrace.core.models.Assertion` that mirrors
the built-in deterministic scorers one-to-one. Use it to construct task packs
in Python instead of hand-writing YAML parameter dicts:

    from tooltrace.dsl import assertions, file_exists, file_contains

    asserts = assertions(
        file_exists("report.md"),
        file_contains("notes.txt", text="BAR", weight=2.0),
    )

Every builder validates its arguments immediately (via pydantic), so typos
surface at authoring time rather than at scoring time. The authoritative
validation remains ``tooltrace validate`` / ``tooltrace lint``.
"""

from __future__ import annotations

from typing import Any

from tooltrace.core.models import Assertion

__all__ = [
    "api_state",
    "assertions",
    "ast_check",
    "command_exit",
    "csv_equals",
    "custom",
    "data_equals",
    "file_contains",
    "file_exists",
    "file_not_contains",
    "file_not_exists",
    "git_diff",
    "json_equals",
    "json_schema",
    "tests_pass",
]


def _build(
    type_: str,
    params: dict[str, Any],
    *,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    return Assertion(type=type_, params=params, weight=weight, description=description)


def assertions(*items: Assertion) -> list[Assertion]:
    """Return the given assertions as a validated list (min length 1)."""
    if not items:
        raise ValueError("at least one assertion is required")
    return list(items)


# ---------------------------------------------------------------------------
# file assertions
# ---------------------------------------------------------------------------


def file_exists(path: str, *, weight: float = 1.0, description: str = "") -> Assertion:
    return _build("file_exists", {"path": path}, weight=weight, description=description)


def file_not_exists(path: str, *, weight: float = 1.0, description: str = "") -> Assertion:
    return _build("file_not_exists", {"path": path}, weight=weight, description=description)


def file_contains(
    path: str,
    *,
    text: str | None = None,
    any_of: list[str] | None = None,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    """Pass when ``text`` (or any pattern in ``any_of``) appears in the file."""
    params: dict[str, Any] = {"path": path}
    if text is not None:
        params["text"] = text
    if any_of is not None:
        params["any_of"] = any_of
    return _build("file_contains", params, weight=weight, description=description)


def file_not_contains(
    path: str,
    *,
    text: str | None = None,
    none_of: list[str] | None = None,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    """Pass when ``text`` (or every pattern in ``none_of``) is absent."""
    params: dict[str, Any] = {"path": path}
    if text is not None:
        params["text"] = text
    if none_of is not None:
        params["none_of"] = none_of
    return _build("file_not_contains", params, weight=weight, description=description)


# ---------------------------------------------------------------------------
# structured data assertions
# ---------------------------------------------------------------------------


def json_schema(
    path: str, schema: dict[str, Any], *, weight: float = 1.0, description: str = ""
) -> Assertion:
    return _build(
        "json_schema", {"path": path, "schema": schema}, weight=weight, description=description
    )


def json_equals(
    path: str, expected: Any, *, weight: float = 1.0, description: str = ""
) -> Assertion:
    return _build(
        "json_equals", {"path": path, "expected": expected}, weight=weight, description=description
    )


def csv_equals(
    path: str, expected_csv: str, *, weight: float = 1.0, description: str = ""
) -> Assertion:
    return _build(
        "csv_equals",
        {"path": path, "expected_csv": expected_csv},
        weight=weight,
        description=description,
    )


def data_equals(
    path: str, expected: str, *, weight: float = 1.0, description: str = ""
) -> Assertion:
    """Whitespace-normalized full-content equality against inline expected text."""
    return _build(
        "data_equals", {"path": path, "expected": expected}, weight=weight, description=description
    )


def ast_check(
    path: str,
    *,
    defines: list[str] | None = None,
    not_defines: list[str] | None = None,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    params: dict[str, Any] = {"path": path}
    if defines is not None:
        params["defines"] = defines
    if not_defines is not None:
        params["not_defines"] = not_defines
    return _build("ast_check", params, weight=weight, description=description)


# ---------------------------------------------------------------------------
# command / test / git / api assertions
# ---------------------------------------------------------------------------


def command_exit(
    command: str,
    *,
    expect_code: int = 0,
    timeout_seconds: float = 30.0,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    return _build(
        "command_exit",
        {"command": command, "expect_code": expect_code, "timeout_seconds": timeout_seconds},
        weight=weight,
        description=description,
    )


def tests_pass(
    path: str = ".",
    *,
    min_ratio: float = 1.0,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    return _build(
        "tests_pass",
        {"path": path, "min_ratio": min_ratio},
        weight=weight,
        description=description,
    )


def git_diff(
    *,
    contains: list[str] | None = None,
    not_contains: list[str] | None = None,
    max_changed_files: int | None = None,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    params: dict[str, Any] = {}
    if contains is not None:
        params["contains"] = contains
    if not_contains is not None:
        params["not_contains"] = not_contains
    if max_changed_files is not None:
        params["max_changed_files"] = max_changed_files
    return _build("git_diff", params, weight=weight, description=description)


def api_state(
    json_path: str,
    equals: Any,
    *,
    file: str = "state.json",
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    return _build(
        "api_state",
        {"file": file, "json_path": json_path, "equals": equals},
        weight=weight,
        description=description,
    )


def custom(
    type_name: str,
    params: dict[str, Any],
    *,
    weight: float = 1.0,
    description: str = "",
) -> Assertion:
    """Escape hatch for third-party scorers registered via ``tooltrace.scorers``."""
    return _build(type_name, dict(params), weight=weight, description=description)
