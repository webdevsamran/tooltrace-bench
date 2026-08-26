"""Versioning for ToolTrace Bench.

Four independent version axes (see ARCHITECTURE.md):

- ``FRAMEWORK_VERSION``      — the tooltrace-bench package itself (semver).
- ``TASK_PROTOCOL_VERSION``  — the task-definition protocol. Tasks and results
  from different protocol versions are never compared.
- ``TASK_SCHEMA_VERSION``    — the JSON Schema revision for task YAML files.
- ``TRACE_SCHEMA_VERSION`` / ``RESULT_SCHEMA_VERSION`` — artifact formats.
"""

from __future__ import annotations

FRAMEWORK_VERSION = "0.2.1"
TASK_PROTOCOL_VERSION = 1
TASK_SCHEMA_VERSION = 1
TRACE_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1

SCHEMA_VERSIONS: dict[str, int] = {
    "task": TASK_SCHEMA_VERSION,
    "trace": TRACE_SCHEMA_VERSION,
    "result": RESULT_SCHEMA_VERSION,
}


def compatibility_key() -> str:
    """Key used to gate comparisons: only identical keys may be compared."""
    return (
        f"protocol={TASK_PROTOCOL_VERSION};"
        f"trace={TRACE_SCHEMA_VERSION};"
        f"result={RESULT_SCHEMA_VERSION}"
    )
