"""Validate a written bundle against the schemas the project publishes.

`schemas/` has always carried four documents, and only `task.schema.json` was
ever enforced. `result.schema.json`, `trace.schema.json` and
`bundle-manifest.schema.json` were decorative: nothing in the runtime, the test
suite or CI ever checked an artifact against them, so they could drift from the
artifacts they claimed to describe without anything noticing.

Turning enforcement on was empirically free — every bundle committed to this
repository already validates — which is the point: the schemas were right, they
just were not load-bearing.

One invariant deliberately lives here rather than in a schema. A JSON Schema
validates one document, and `trace.jsonl` is a stream, so no schema can say
"`seq` is unique and strictly increasing across the file". `validate_trace_stream`
does, because that invariant is what partial replay partitions on.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tooltrace.core.schemas import load_schema


def _errors(doc: object, schema_name: str, label: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema(schema_name))
    return [
        f"{label}: {e.message}" for e in sorted(validator.iter_errors(doc), key=lambda e: str(e))
    ]


def validate_result_document(doc: object) -> list[str]:
    """Validate one `result.json` document."""
    return _errors(doc, "result", "result.json")


def validate_manifest_document(doc: object) -> list[str]:
    """Validate one `manifest.json` document."""
    return _errors(doc, "bundle-manifest", "manifest.json")


def validate_trace_line(doc: object, line_number: int = 1) -> list[str]:
    """Validate one line of `trace.jsonl`."""
    return _errors(doc, "trace", f"trace.jsonl:{line_number}")


def validate_trace_stream(lines: list[dict[str, object]]) -> list[str]:
    """Validate every event, plus the stream invariants a schema cannot express."""
    problems: list[str] = []
    for index, event in enumerate(lines, start=1):
        problems.extend(validate_trace_line(event, index))

    seqs = [event.get("seq") for event in lines]
    if any(s is None for s in seqs):
        problems.append("trace.jsonl: every event needs a seq")
        return problems

    numbered = [int(s) for s in seqs if isinstance(s, int)]
    duplicates = sorted({s for s in numbered if numbered.count(s) > 1})
    if duplicates:
        problems.append(f"trace.jsonl: seq must be unique within a trace; repeated {duplicates}")
    elif numbered != sorted(numbered):
        problems.append("trace.jsonl: seq must increase monotonically in file order")
    elif numbered and numbered != list(range(1, len(numbered) + 1)):
        problems.append(f"trace.jsonl: seq must run 1..{len(numbered)} with no gaps")
    return problems


def validate_bundle_artifacts(bundle_dir: Path) -> list[str]:
    """Validate `result.json`, `trace.jsonl` and `manifest.json` in one bundle.

    Missing or unreadable files are reported rather than raised, so a caller
    gets every problem at once instead of only the first.
    """
    problems: list[str] = []

    result_path = bundle_dir / "result.json"
    if not result_path.is_file():
        problems.append("result.json: missing")
    else:
        try:
            problems.extend(validate_result_document(json.loads(result_path.read_text("utf-8"))))
        except json.JSONDecodeError as exc:
            problems.append(f"result.json: not valid JSON ({exc})")

    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        problems.append("manifest.json: missing")
    else:
        try:
            problems.extend(
                validate_manifest_document(json.loads(manifest_path.read_text("utf-8")))
            )
        except json.JSONDecodeError as exc:
            problems.append(f"manifest.json: not valid JSON ({exc})")

    trace_path = bundle_dir / "trace.jsonl"
    if not trace_path.is_file():
        problems.append("trace.jsonl: missing")
    else:
        events: list[dict[str, object]] = []
        for index, raw in enumerate(trace_path.read_text("utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                problems.append(f"trace.jsonl:{index}: not valid JSON ({exc})")
        problems.extend(validate_trace_stream(events))

    return problems
