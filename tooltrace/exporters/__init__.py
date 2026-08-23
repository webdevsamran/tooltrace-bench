"""Exporter plugin API.

Reporters registered under the ``tooltrace.reporters`` entry-point group are
callables ``(payload: dict, dest_dir: Path) -> Path`` that write one report
file and return its path. This package provides:

- ``register_exporter`` / ``run_exporters`` — in-process registration and
  execution of exporters;
- built-in file-writing reporters (``json_report``, ``csv_report``,
  ``markdown_report``, ``junit_report``, ``html_report``) that wrap
  :mod:`tooltrace.reports` and are declared as entry points so third parties
  can mirror the same contract.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from tooltrace.reports import FORMATS

Exporter = Callable[[dict[str, Any], Path], Path]
_EXPORTERS: dict[str, Exporter] = {}


def register_exporter(name: str, fn: Exporter) -> Exporter:
    """Register an exporter under *name* (in-process variant of entry points)."""
    _EXPORTERS[name] = fn
    return fn


def run_exporters(payload: dict[str, Any], dest_dir: Path) -> list[str]:
    """Run all registered exporters plus any entry-point plugins."""
    from tooltrace.core.registry import discover_plugins

    produced: list[str] = []
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in {**_EXPORTERS, **discover_plugins("tooltrace.reporters")}.items():
        try:
            out = fn(payload, dest_dir)
            produced.append(str(out))
        except Exception as exc:
            produced.append(f"{name}: ERROR {exc}")
    return produced


def _file_writer(fmt: str) -> Exporter:
    def write(payload: dict[str, Any], dest_dir: Path) -> Path:
        from tooltrace.reports import export_report

        target = dest_dir / f"report.{fmt}"
        export_report(payload, fmt, target)
        return target

    return write


json_report = _file_writer("json")
csv_report = _file_writer("csv")
markdown_report = _file_writer("md")
junit_report = _file_writer("junit")
html_report = _file_writer("html")

__all__ = [
    "FORMATS",
    "csv_report",
    "html_report",
    "json_report",
    "junit_report",
    "markdown_report",
    "register_exporter",
    "run_exporters",
]
