"""Analysis, baselines, trends, clustering, leaderboards and provenance
(features 69-71, 76-91 subset implemented deterministically).

- regression baselines at suite/domain/task/metric level with tolerances;
- trend analysis across versions with task-set composition warnings;
- cohort compatibility rules so incompatible protocol/scorer/task versions are
  never silently compared;
- deterministic failure clustering from feature vectors;
- leaderboard cohorts + anti-gaming checks;
- reproducibility score from metadata completeness (explicitly NOT a
  scientific-validity score);
- invalidation/supersession records instead of silent deletion;
- dataset snapshots with changelogs, counts and hashes;
- tamper-evident checksums and signed bundles via external standard tooling
  (cosign) when available - never custom cryptography.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tooltrace.tasks.governance import canonical_json, sha256_text, utc_now_iso

# ---------------------------------------------------------------------------
# Cohort compatibility (features 69, 89)
# ---------------------------------------------------------------------------


def cohort_key(result: Mapping[str, Any]) -> str:
    """Cohort identity: tasks must share protocol, scorer version and the same
    task-set fingerprint to be ranked or compared together."""
    return "|".join(
        (
            str(result.get("protocol_version", "unknown")),
            str(result.get("scoring_version", "unknown")),
            str(result.get("task_set_sha256", "unknown")),
        )
    )


def assert_compatible_cohorts(
    results_a: Sequence[Mapping[str, Any]], results_b: Sequence[Mapping[str, Any]]
) -> None:
    ka = {cohort_key(r) for r in results_a}
    kb = {cohort_key(r) for r in results_b}
    if not ka or not kb:
        raise ValueError("empty result sets cannot form a comparison cohort")
    if not (ka & kb):
        raise ValueError(
            f"incompatible cohorts {sorted(ka)} vs {sorted(kb)}: "
            "protocol/scorer/task-set versions differ; refusing to compare"
        )


# ---------------------------------------------------------------------------
# Regression baselines (feature 70)
# ---------------------------------------------------------------------------


class Baseline(BaseModel):
    baseline_id: str
    scope: str  # suite | domain | task | metric
    scope_key: str
    metrics: dict[str, float]
    tolerance: dict[str, float] = Field(default_factory=dict)  # metric -> abs tol
    default_tolerance: float = 0.02
    created_at: str = Field(default_factory=utc_now_iso)
    baseline_sha256: str = ""

    def finalize(self) -> Baseline:
        self.baseline_sha256 = sha256_text(
            canonical_json(self.model_dump(mode="json", exclude={"baseline_sha256"}))
        )
        return self


def evaluate_against_baseline(current: Mapping[str, float], baseline: Baseline) -> dict[str, Any]:
    """CI-gate style evaluation: regressions beyond tolerance are failures."""
    failures: list[dict[str, Any]] = []
    for metric, base_value in baseline.metrics.items():
        if metric not in current:
            continue
        tol = baseline.tolerance.get(metric, baseline.default_tolerance)
        delta = current[metric] - base_value
        if delta < -tol:
            failures.append(
                {
                    "metric": metric,
                    "baseline": base_value,
                    "current": current[metric],
                    "delta": round(delta, 6),
                    "tolerance": tol,
                }
            )
    return {"ok": not failures, "regressions": failures}


# ---------------------------------------------------------------------------
# Trend analysis (feature 71)
# ---------------------------------------------------------------------------


def trend_analysis(
    points: Sequence[Mapping[str, Any]], metric: str = "success_rate"
) -> dict[str, Any]:
    """Ordered trend across agent/model versions with composition warnings when
    the underlying task set changed between consecutive points."""
    ordered = sorted(points, key=lambda p: str(p.get("version", "")))
    series: list[dict[str, Any]] = []
    warnings: list[str] = []
    prev_set: str | None = None
    for p in ordered:
        entry: dict[str, Any] = {
            "version": p.get("version"),
            "metric": p.get(metric),
            "n_tasks": p.get("n_tasks"),
            "task_set_sha256": p.get("task_set_sha256"),
        }
        if prev_set is not None and p.get("task_set_sha256") != prev_set:
            warnings.append(
                f"task set changed at version {p.get('version')}; trend is not like-for-like"
            )
        prev_set = p.get("task_set_sha256")
        series.append(entry)
    return {"metric": metric, "series": series, "composition_warnings": warnings}


# ---------------------------------------------------------------------------
# Failure clustering (feature 76) - deterministic feature vectors first
# ---------------------------------------------------------------------------


def cluster_failures(results: Sequence[Mapping[str, Any]], max_clusters: int = 8) -> dict[str, Any]:
    """Cluster failed runs by deterministic features: failing assertion types,
    first erroring tool, error-kind signature. No semantic model involved."""
    clusters: dict[str, list[str]] = {}
    for r in results:
        if r.get("success"):
            continue
        sig_parts = [
            ",".join(sorted(r.get("failed_assertions", []) or [])),
            str(r.get("first_error_tool", "none")),
            str(r.get("error_kind", "none")),
        ]
        signature = " | ".join(sig_parts)
        clusters.setdefault(signature, []).append(str(r.get("run_id", "?")))
    ranked = sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:max_clusters]
    return {
        "clusters": [{"signature": sig, "size": len(ids), "run_ids": ids} for sig, ids in ranked],
        "clustered_failures": sum(len(v) for v in clusters.values()),
        "method": "deterministic-feature-signature",
    }


# ---------------------------------------------------------------------------
# Leaderboards + anti-gaming (features 89, 90, 91)
# ---------------------------------------------------------------------------


def build_leaderboard(
    results: Sequence[Mapping[str, Any]], metric: str = "success_rate"
) -> dict[str, Any]:
    """Separate leaderboards per cohort; never mixes incompatible versions."""
    by_cohort: dict[str, list[Mapping[str, Any]]] = {}
    for r in results:
        by_cohort.setdefault(cohort_key(r), []).append(r)
    boards: dict[str, list[dict[str, Any]]] = {}
    for key, rows in sorted(by_cohort.items()):
        entries = []
        for r in rows:
            entries.append(
                {
                    "agent": r.get("agent", "unknown"),
                    "score": r.get(metric),
                    "runs": r.get("runs"),
                    "reproducibility_score": r.get("reproducibility_score"),
                }
            )
        entries.sort(key=lambda e: -(e["score"] or 0))
        boards[key] = entries
    return {"metric": metric, "cohorts": list(boards.keys()), "leaderboards": boards}


def anti_gaming_checks(
    result: Mapping[str, Any], expected_task_hashes: Mapping[str, str]
) -> dict[str, Any]:
    """Detect leaked expected outputs, modified fixtures, skipped assertions."""
    problems: list[str] = []
    checked = set(
        result.get("assertion_results", [])
        and [a.get("type") for a in result.get("assertion_results", [])]
    )
    declared = set(result.get("declared_assertions", []) or [])
    skipped = declared - checked
    if skipped:
        problems.append(f"assertions declared but absent from results: {sorted(skipped)}")
    for tid, want in expected_task_hashes.items():
        got = (result.get("task_hashes") or {}).get(tid)
        if got is not None and got != want:
            problems.append(f"fixture hash mismatch for {tid}: fixture modified after publication")
    if (
        result.get("harness_sha256")
        and result.get("expected_harness_sha256")
        and result["harness_sha256"] != result["expected_harness_sha256"]
    ):
        problems.append("benchmark harness hash differs from published harness")
    if any(
        "ANSWER:" in str(a.get("output", ""))[:2000] for a in result.get("assertion_results", [])
    ):
        problems.append("possible leaked expected output embedded in agent output")
    return {"ok": not problems, "problems": problems}


# ---------------------------------------------------------------------------
# Reproducibility score (feature 78)
# ---------------------------------------------------------------------------

REPRO_FIELDS = (
    "task_pack_version",
    "protocol_version",
    "scoring_version",
    "model_revision",
    "sampling_settings",
    "sandbox_image_digest",
    "seed",
    "environment_manifest_sha256",
)


def reproducibility_score(result: Mapping[str, Any]) -> dict[str, Any]:
    """Metadata-completeness score 0..1. Explicitly NOT scientific validity."""
    present = [f for f in REPRO_FIELDS if result.get(f) not in (None, "", {}, [])]
    missing = [f for f in REPRO_FIELDS if f not in present]
    return {
        "score": round(len(present) / len(REPRO_FIELDS), 4),
        "present": present,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Invalidation / supersession (feature 87)
# ---------------------------------------------------------------------------


class InvalidationRecord(BaseModel):
    record_id: str
    target_id: str  # bundle/result being invalidated
    reason: str
    superseded_by: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    author: str = "maintainer"
    record_sha256: str = ""

    def finalize(self) -> InvalidationRecord:
        self.record_sha256 = sha256_text(
            canonical_json(self.model_dump(mode="json", exclude={"record_sha256"}))
        )
        return self

    def applies_to(self, target_id: str) -> bool:
        return self.target_id == target_id


# ---------------------------------------------------------------------------
# Snapshots (feature 88)
# ---------------------------------------------------------------------------


def generate_snapshot(source_dir: Path, output_path: Path, changelog: str) -> dict[str, Any]:
    """Reproducible public dataset snapshot: index of files with hashes."""
    files: list[dict[str, str]] = []
    for path in sorted(Path(source_dir).rglob("*")):
        if path.is_file() and ".git" not in path.parts:
            data = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(source_dir).as_posix(),
                    "bytes": str(len(data)),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    snapshot = {
        "snapshot_version": 1,
        "created_at": utc_now_iso(),
        "changelog": changelog,
        "file_count": len(files),
        "files": files,
    }
    snapshot["snapshot_sha256"] = sha256_text(canonical_json(snapshot))
    Path(output_path).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return snapshot


def verify_snapshot(snapshot_path: Path, source_dir: Path) -> list[str]:
    """Verify files still match a published snapshot; returns mismatches."""
    snap = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    problems: list[str] = []
    for entry in snap["files"]:
        f = Path(source_dir) / entry["path"]
        if not f.exists():
            problems.append(f"missing: {entry['path']}")
            continue
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            problems.append(f"hash mismatch: {entry['path']}")
    return problems


# ---------------------------------------------------------------------------
# Signing via standard tooling (feature 85)
# ---------------------------------------------------------------------------


def sign_bundle(bundle_path: Path, signer: str = "cosign") -> dict[str, Any]:
    """Sign a bundle with an external standard tool (default: cosign
    sign-blob). Never implements custom crypto. Returns honest status when the
    tool is unavailable."""
    tool = shutil.which(signer)
    if tool is None:
        return {"signed": False, "reason": f"{signer} not installed; bundle left unsigned"}
    sig_path = Path(str(bundle_path) + ".sig")
    try:
        proc = subprocess.run(
            [tool, "sign-blob", "--yes", "--output-signature", str(sig_path), str(bundle_path)],
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"signed": False, "reason": f"{signer} timed out"}
    if proc.returncode != 0:
        return {"signed": False, "reason": proc.stderr.decode("utf-8", "replace")[:300]}
    return {"signed": True, "signature_path": str(sig_path), "signer": signer}


def verify_bundle_signature(
    bundle_path: Path, signature_path: Path, signer: str = "cosign"
) -> dict[str, Any]:
    tool = shutil.which(signer)
    if tool is None:
        return {"verified": False, "reason": f"{signer} not installed"}
    try:
        proc = subprocess.run(
            [tool, "verify-blob", "--signature", str(signature_path), str(bundle_path)],
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"verified": False, "reason": f"{signer} timed out"}
    return {"verified": proc.returncode == 0, "signer": signer}


# ---------------------------------------------------------------------------
# Tamper-evident checksums (feature 86)
# ---------------------------------------------------------------------------


def manifest_checksums(manifests: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Checksum map for task/fixture/trace/score/environment manifests."""
    return {
        str(m.get("id", i)): sha256_text(canonical_json(dict(m))) for i, m in enumerate(manifests)
    }


def detect_tampering(
    manifests: Sequence[Mapping[str, Any]], recorded: Mapping[str, str]
) -> list[str]:
    current = manifest_checksums(manifests)
    return [mid for mid, digest in recorded.items() if current.get(mid) != digest]


__all__ = [
    "Baseline",
    "InvalidationRecord",
    "anti_gaming_checks",
    "assert_compatible_cohorts",
    "build_leaderboard",
    "cluster_failures",
    "cohort_key",
    "detect_tampering",
    "evaluate_against_baseline",
    "generate_snapshot",
    "manifest_checksums",
    "reproducibility_score",
    "sign_bundle",
    "trend_analysis",
    "verify_bundle_signature",
    "verify_snapshot",
]
