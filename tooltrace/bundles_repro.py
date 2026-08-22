"""Bundle reproduction: verify a bundle, then re-run the task when the
prerequisites (task fixtures, agent adapter) are available locally.

Reproduction updates the bundle's trust state to REPRODUCED only when the
re-run succeeds and checksums were valid beforehand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tooltrace.bundles import (
    load_bundle_result,
    load_bundle_task,
    verify_bundle,
    write_bundle,
)
from tooltrace.core.exceptions import BundleError
from tooltrace.core.models import TrustState


@dataclass(frozen=True)
class ReproductionReport:
    bundle: str
    verified: bool
    problems: list[str]
    rerun_attempted: bool
    rerun_success: bool | None
    new_bundle: str | None = None
    message: str = ""


def reproduce_bundle(
    bundle_dir: Path,
    out_dir: Path | None = None,
    rerun: bool = True,
) -> ReproductionReport:
    from tooltrace.runners.runner import TaskRunner

    problems = verify_bundle(bundle_dir)
    if problems:
        return ReproductionReport(
            bundle=str(bundle_dir),
            verified=False,
            problems=problems,
            rerun_attempted=False,
            rerun_success=None,
            message="bundle failed verification; refusing to reproduce",
        )

    result = load_bundle_result(bundle_dir)
    task = load_bundle_task(bundle_dir)

    if not rerun:
        return ReproductionReport(
            bundle=str(bundle_dir),
            verified=True,
            problems=[],
            rerun_attempted=False,
            rerun_success=None,
            message="checksums verified; rerun skipped (--no-rerun)",
        )

    try:
        runner = TaskRunner(output_dir=out_dir)
        new_result, events, diff_text = runner.run(
            task,
            agent_name=result.agent,
            agent_config=dict(result.agent_config),
        )
    except Exception as exc:
        return ReproductionReport(
            bundle=str(bundle_dir),
            verified=True,
            problems=[],
            rerun_attempted=True,
            rerun_success=None,
            message=f"rerun failed to execute: {exc}",
        )

    # Score details for the new bundle.

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        new_bundle = write_bundle(Path(tmp), new_result, events, task, diff_text, {})
        new_name = new_bundle.name
    if out_dir is not None:
        final_bundle = write_bundle(out_dir, new_result, events, task, diff_text, {})
        new_name = final_bundle.name

    match = (
        new_result.success == result.success
        and abs(new_result.score.total - result.score.total) < 1e-9
    )
    return ReproductionReport(
        bundle=str(bundle_dir),
        verified=True,
        problems=[],
        rerun_attempted=True,
        rerun_success=new_result.success,
        new_bundle=new_name,
        message=(
            "reproduced: outcome and score match"
            if match
            else "rerun completed but outcome/score differ from the original bundle"
        ),
    )


def promote_trust(bundle_dir: Path, state: TrustState) -> None:
    """Set a bundle's trust state in its manifest and result.json.

    Only call with evidence. Never implies verification without proof.
    """
    import json

    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trust_state"] = state.value
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    result_path = bundle_dir / "result.json"
    result_data = json.loads(result_path.read_text(encoding="utf-8"))
    result_data["trust_state"] = state.value
    result_path.write_text(json.dumps(result_data, indent=2), encoding="utf-8")


def require_verified(bundle_dir: Path) -> None:
    problems = verify_bundle(bundle_dir)
    if problems:
        raise BundleError("; ".join(problems))
