"""Task governance: provenance manifests, versioned pack indexes with
compatibility ranges, fingerprint deduplication across packs.

Every artifact produced here carries schema/producer versions, UTC timestamp,
deterministic ID/fingerprint, checksums and verification state (DATA/PROTOCOL
GOVERNANCE rule).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tooltrace.core.versions import FRAMEWORK_VERSION, TASK_PROTOCOL_VERSION

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization used for all fingerprints/hashes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Provenance manifests (feature 2)
# ---------------------------------------------------------------------------


class FixtureOrigin(BaseModel):
    source: str  # e.g. "authored", "derived:<repo>", "synthetic-template"
    license: str = "Apache-2.0"
    method: str = ""  # how the fixture was created
    repository: str = ""  # upstream repo URL if derived
    revision: str = ""  # upstream commit/tag if derived


class FixtureProvenance(BaseModel):
    path: str
    sha256: str
    origin: FixtureOrigin


class ProvenanceManifest(BaseModel):
    schema_version: int = 1
    producer: str = f"tooltrace-bench {FRAMEWORK_VERSION}"
    created_at: str = Field(default_factory=utc_now_iso)
    task_id: str
    task_version: str
    task_sha256: str  # hash of the canonical task definition
    fixtures: list[FixtureProvenance] = Field(default_factory=list)
    manifest_sha256: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("manifest_sha256", None)
        return sha256_text(canonical_json(payload))


def build_provenance_manifest(
    task: Any, origins: dict[str, FixtureOrigin] | None = None
) -> ProvenanceManifest:
    """Build a provenance manifest for a task (v1 or v2).

    ``origins`` maps fixture path -> origin; unlisted fixtures get a default
    'authored' origin. Integrity hashes cover fixture contents.
    """
    origins = origins or {}
    fixtures: list[FixtureProvenance] = []
    for path, content in sorted(dict(getattr(task, "fixtures", {}) or {}).items()):
        fixtures.append(
            FixtureProvenance(
                path=path,
                sha256=sha256_text(content),
                origin=origins.get(path, FixtureOrigin(source="authored")),
            )
        )
    manifest = ProvenanceManifest(
        task_id=str(task.id),
        task_version=str(getattr(task, "version", "1.0.0")),
        task_sha256=sha256_text(canonical_json(_task_payload(task))),
        fixtures=fixtures,
    )
    manifest.manifest_sha256 = manifest.compute_checksum()
    return manifest


def verify_provenance_manifest(manifest: ProvenanceManifest, task: Any) -> list[str]:
    """Return a list of integrity problems (empty list == verified)."""
    problems: list[str] = []
    if manifest.manifest_sha256 != manifest.compute_checksum():
        problems.append("manifest checksum mismatch (manifest was modified)")
    if manifest.task_sha256 != sha256_text(canonical_json(_task_payload(task))):
        problems.append(f"task definition hash mismatch for {manifest.task_id}")
    fixtures = dict(getattr(task, "fixtures", {}) or {})
    for fp in manifest.fixtures:
        actual = fixtures.get(fp.path)
        if actual is None:
            problems.append(f"fixture missing from task: {fp.path}")
        elif sha256_text(actual) != fp.sha256:
            problems.append(f"fixture content hash mismatch: {fp.path}")
    return problems


def _task_payload(task: Any) -> dict[str, Any]:
    dump = task.model_dump(mode="json") if hasattr(task, "model_dump") else dict(task)
    dump.pop("metadata", None)  # metadata may carry run-specific extras
    return dump


# ---------------------------------------------------------------------------
# Versioned pack indexes (feature 3)
# ---------------------------------------------------------------------------


class PackIndexEntry(BaseModel):
    task_id: str
    task_version: str
    definition_sha256: str


class PackIndex(BaseModel):
    schema_version: int = 1
    producer: str = f"tooltrace-bench {FRAMEWORK_VERSION}"
    created_at: str = Field(default_factory=utc_now_iso)
    pack: str
    index_version: str  # semver of the index itself
    protocol_versions: list[int] = Field(default_factory=lambda: [TASK_PROTOCOL_VERSION])
    compatible_framework_range: str = f">={FRAMEWORK_VERSION}"
    tasks: list[PackIndexEntry] = Field(default_factory=list)
    index_sha256: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("index_sha256", None)
        return sha256_text(canonical_json(payload))


def parse_semver(version: str) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def satisfies_range(version: str, range_spec: str) -> bool:
    """Minimal semver range support: '>=X.Y.Z', '<=X.Y.Z', '==X.Y.Z' joined
    by commas (AND). Unknown formats fail closed."""
    parsed = parse_semver(version)
    if parsed is None:
        return False
    for clause in range_spec.split(","):
        clause = clause.strip()
        m = re.match(r"^(>=|<=|==)(.+)$", clause)
        if not m:
            return False
        bound = parse_semver(m.group(2))
        if bound is None:
            return False
        op = m.group(1)
        if op == ">=" and not parsed >= bound:
            return False
        if op == "<=" and not parsed <= bound:
            return False
        if op == "==" and parsed != bound:
            return False
    return True


def build_pack_index(pack: str, tasks: list[Any], index_version: str = "1.0.0") -> PackIndex:
    entries = [
        PackIndexEntry(
            task_id=str(t.id),
            task_version=str(getattr(t, "version", "1.0.0")),
            definition_sha256=sha256_text(canonical_json(_task_payload(t))),
        )
        for t in sorted(tasks, key=lambda x: str(x.id))
    ]
    idx = PackIndex(pack=pack, index_version=index_version, tasks=entries)
    idx.index_sha256 = idx.compute_checksum()
    return idx


# ---------------------------------------------------------------------------
# Fingerprint dedup across packs (feature 5)
# ---------------------------------------------------------------------------


def task_fingerprint(task: Any) -> str:
    """Deterministic fingerprint from normalized objective, fixtures and
    assertion graph. Two tasks with identical fingerprints are duplicates even
    across packs."""
    objective = re.sub(r"\s+", " ", str(getattr(task, "objective", "")).strip().lower())
    fixtures = {
        p: sha256_text(c) for p, c in sorted(dict(getattr(task, "fixtures", {}) or {}).items())
    }
    workspace = {
        p: sha256_text(c)
        for p, c in sorted(dict(getattr(task, "starting_workspace", {}) or {}).items())
    }
    assertion_graph = []
    for a in getattr(task, "assertions", []) or []:
        params = a.params if hasattr(a, "params") else a.get("params", {})
        assertion_graph.append(
            {"type": getattr(a, "type", None) or a.get("type"), "params": params}
        )
    payload = {
        "objective": objective,
        "fixtures": fixtures,
        "workspace": workspace,
        "assertions": assertion_graph,
    }
    return sha256_text(canonical_json(payload))


def find_duplicates(tasks: list[Any]) -> list[list[str]]:
    """Group task ids sharing identical fingerprints (only multi-member groups)."""
    groups: dict[str, list[str]] = {}
    for t in tasks:
        groups.setdefault(task_fingerprint(t), []).append(str(t.id))
    return sorted(g for g in groups.values() if len(g) > 1)


# ---------------------------------------------------------------------------
# Dataset snapshots (feature 88) live with governance because they share the
# canonical hashing helpers.
# ---------------------------------------------------------------------------


class SnapshotEntry(BaseModel):
    artifact: str
    sha256: str
    count: int = 0


class DatasetSnapshot(BaseModel):
    schema_version: int = 1
    created_at: str = Field(default_factory=utc_now_iso)
    snapshot_id: str
    compatibility_key: str
    changelog: str = ""
    counts: dict[str, int] = Field(default_factory=dict)
    artifacts: list[SnapshotEntry] = Field(default_factory=list)
    snapshot_sha256: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("snapshot_sha256", None)
        return sha256_text(canonical_json(payload))


def build_snapshot(
    snapshot_id: str,
    files: list[tuple[str, Path]],
    changelog: str = "",
    counts: dict[str, int] | None = None,
) -> DatasetSnapshot:
    entries = []
    for name, path in sorted(files):
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        entries.append(
            SnapshotEntry(
                artifact=name, sha256=hashlib.sha256(data).hexdigest(), count=text.count("\n")
            )
        )
    snap = DatasetSnapshot(
        snapshot_id=snapshot_id,
        compatibility_key=_compat_key(),
        changelog=changelog,
        counts=dict(counts or {}),
        artifacts=entries,
    )
    snap.snapshot_sha256 = snap.compute_checksum()
    return snap


def _compat_key() -> str:
    from tooltrace.core.versions import compatibility_key

    return compatibility_key()


# ---------------------------------------------------------------------------
# Contamination-aware metadata (feature 4)
# ---------------------------------------------------------------------------


class ContaminationFlag(BaseModel):
    """Author-declared public training-exposure risk for a task.

    This is an honest risk signal, not proof: benchmark authors flag tasks whose
    objectives/fixtures may appear in public training corpora. Levels:
    none | low | medium | high. Verification state is always 'declared'.
    """

    task_id: str
    level: str = "none"  # none | low | medium | high
    reason: str = ""
    public_sources: list[str] = Field(default_factory=list)
    declared_at: str = Field(default_factory=utc_now_iso)
    verification_state: str = "declared"


def assess_contamination(
    task_id: str,
    *,
    objective_text: str = "",
    fixture_names: list[str] | None = None,
    derived_from_public_repo: bool = False,
    known_leak_reports: list[str] | None = None,
) -> ContaminationFlag:
    """Heuristic contamination-risk assessment from declared evidence.

    Combines author declarations (derived-from-public, leak reports) with simple
    textual signals (generic phrasing, well-known filenames). Never claims a
    task is clean; absence of evidence yields level 'none' only when no signals
    exist in the supplied evidence.
    """
    score = 0
    reasons: list[str] = []
    sources: list[str] = list(known_leak_reports or [])
    if derived_from_public_repo:
        score += 3
        reasons.append("fixtures/objectives derived from a public repository")
    if known_leak_reports:
        score += 4
        reasons.append("public leak reports exist for this content")
    text = (objective_text or "").lower()
    generic_markers = (
        "fizzbuzz",
        "two sum",
        "reverse a string",
        "fibonacci",
        "palindrome",
        "todo app",
        "hello world",
    )
    if any(m in text for m in generic_markers):
        score += 2
        reasons.append("objective uses widely duplicated textbook phrasing")
    common_files = {"readme.md", "main.py", "index.js", "app.py", "utils.py"}
    overlap = common_files.intersection({f.lower() for f in (fixture_names or [])})
    if overlap:
        score += 1
        reasons.append(f"generic fixture filenames: {sorted(overlap)}")
    if not reasons:
        return ContaminationFlag(
            task_id=task_id,
            level="none",
            reason="no public-exposure signals in declared evidence",
        )
    level = ("low", "medium", "high")[min(score // 3, 2)]
    return ContaminationFlag(
        task_id=task_id, level=level, reason="; ".join(reasons), public_sources=sources
    )
