"""`.tooltrace` result bundles: write, verify, reproduce.

A bundle is a directory named ``<slug>.tooltrace`` containing:

    result.json       EvalResult
    trace.jsonl       versioned trace events
    task.yaml         the exact task definition used
    environment.json  host metadata
    workspace.diff    unified diff of the workspace
    scoring.json      per-assertion scores and details
    manifest.json     SHA-256 checksums of every file above
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from tooltrace.core.exceptions import BundleError
from tooltrace.core.models import EvalResult, TaskDefinition, TraceEvent
from tooltrace.core.versions import compatibility_key
from tooltrace.runners.runner import environment_metadata

BUNDLE_FILES = [
    "result.json",
    "trace.jsonl",
    "task.yaml",
    "environment.json",
    "workspace.diff",
    "scoring.json",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: The newline every bundle file is written with, on every platform.
#:
#: `Path.write_text` applies the platform's newline translation, so on Windows
#: a line feed becomes a carriage return plus a line feed. The manifest
#: checksums are taken over the bytes that land on disk -- so a bundle produced
#: on Windows hashed its CRLF content and then failed `verify` on every Linux
#: and macOS checkout. CI caught it: the bundles committed here had been
#: unverifiable off-Windows from the moment they were regenerated on one.
#:
#: A benchmark artifact whose checksum depends on the operating system that
#: wrote it is not reproducible, which is the one thing this format promises.
LF = chr(10)


def bundle_slug(result_task_id: str, agent: str, run_id: str) -> str:
    safe_task = result_task_id.replace("/", "-")
    return f"{safe_task}-{agent}-{run_id}"


def write_bundle(
    out_dir: Path,
    result: EvalResult,
    events: list[TraceEvent],
    task: TaskDefinition,
    diff_text: str,
    scoring_details: dict[str, str],
    validate: bool = True,
    agent_config: dict[str, object] | None = None,
) -> Path:
    """Write a bundle and, unless `validate=False`, check it against the schemas.

    The three artifact schemas shipped unenforced for three releases. They are
    checked at write time now, so a bundle that does not match the format this
    project publishes never reaches disk in the first place.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = out_dir / f"{bundle_slug(result.task_id, result.agent, result.run_id)}.tooltrace"
    bundle_dir.mkdir(exist_ok=True)

    (bundle_dir / "result.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8", newline=LF
    )
    (bundle_dir / "trace.jsonl").write_text(
        "".join(e.model_dump_json() + chr(10) for e in events), encoding="utf-8", newline=LF
    )
    (bundle_dir / "task.yaml").write_text(
        yaml.safe_dump(task.model_dump(mode="json"), sort_keys=False), encoding="utf-8", newline=LF
    )
    (bundle_dir / "environment.json").write_text(
        # `agent_config` only supplies the *declared* inference block --
        # backend, engine version, quantization -- none of which the harness can
        # detect. It is labelled as declared in the record itself.
        json.dumps(environment_metadata(agent_config), indent=2),
        encoding="utf-8",
        newline=LF,
    )
    (bundle_dir / "workspace.diff").write_text(diff_text, encoding="utf-8", newline=LF)
    (bundle_dir / "scoring.json").write_text(
        json.dumps(
            {
                "score": result.score.model_dump(),
                "details": scoring_details,
                "success": result.success,
            },
            indent=2,
        ),
        encoding="utf-8",
        newline=LF,
    )

    checksums = {name: _sha256((bundle_dir / name).read_bytes()) for name in BUNDLE_FILES}
    manifest = {
        "bundle_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "framework_version": result.framework_version,
        "compatibility_key": compatibility_key(),
        "trust_state": result.trust_state.value,
        "files": BUNDLE_FILES,
        "checksums": checksums,
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8", newline=LF
    )

    if validate:
        from tooltrace.artifacts.validation import validate_bundle_artifacts

        problems = validate_bundle_artifacts(bundle_dir)
        if problems:
            raise BundleError(
                f"bundle {bundle_dir.name} does not match its published schemas: "
                + "; ".join(problems[:5])
            )
    return bundle_dir


def read_manifest(bundle_dir: Path) -> dict[str, object]:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BundleError(f"missing manifest.json in {bundle_dir}")
    manifest: dict[str, object] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest


def verify_bundle(bundle_dir: Path) -> list[str]:
    """Verify checksums and required files. Returns a list of problems."""
    problems: list[str] = []
    if not bundle_dir.is_dir():
        raise BundleError(f"bundle directory not found: {bundle_dir}")
    try:
        manifest = read_manifest(bundle_dir)
    except BundleError as exc:
        # A directory that is not a bundle is a *problem to report*, not a
        # crash. verify_bundle's contract is to return problems; letting
        # BundleError escape here surfaced a raw traceback to anyone who
        # pointed `tooltrace trace` at the wrong directory.
        return [str(exc)]
    except (json.JSONDecodeError, OSError) as exc:
        return [f"unreadable manifest: {exc}"]
    checksums = manifest.get("checksums", {})
    if not isinstance(checksums, dict):
        return ["manifest checksums section invalid"]
    for name, expected in checksums.items():
        f = bundle_dir / str(name)
        if not f.is_file():
            problems.append(f"missing file: {name}")
            continue
        actual = _sha256(f.read_bytes())
        if actual != expected:
            problems.append(f"checksum mismatch: {name}")
    for name in BUNDLE_FILES:
        if name not in checksums:
            problems.append(f"manifest does not cover: {name}")
    return problems


def load_bundle_result(bundle_dir: Path) -> EvalResult:
    from tooltrace.core.models import EvalResult

    data = json.loads((bundle_dir / "result.json").read_text(encoding="utf-8"))
    return EvalResult.model_validate(data)


def load_bundle_task(bundle_dir: Path) -> TaskDefinition:
    doc = yaml.safe_load((bundle_dir / "task.yaml").read_text(encoding="utf-8"))
    return TaskDefinition.model_validate(doc)


def load_bundle_trace(bundle_dir: Path) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for line in (bundle_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(TraceEvent.model_validate(json.loads(line)))
    return events
