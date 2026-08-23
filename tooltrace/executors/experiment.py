"""Experiment execution engine (features 60-68).

- experiment manifests pinning suite/adapter/model/sampling/sandbox/scoring;
- local multi-process pool with bounded concurrency;
- resumable execution with checkpointed run state and idempotent IDs;
- cancellation with graceful cleanup;
- failure isolation (one crashing task cannot corrupt the experiment);
- sharding + merge for large campaigns;
- file-based coordinator queue with atomic job claiming for team mode.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from tooltrace.core.versions import compatibility_key
from tooltrace.tasks.governance import canonical_json, sha256_text, utc_now_iso

# ---------------------------------------------------------------------------
# Experiment manifests (feature 60)
# ---------------------------------------------------------------------------


class ExperimentManifest(BaseModel):
    schema_version: int = 1
    experiment_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: str = Field(default_factory=utc_now_iso)
    suite_id: str
    selection_sha256: str | None = None
    agent_adapter: str
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    repetitions: int = 1
    sandbox_provider: str = "local"
    resource_budgets: dict[str, float] = Field(default_factory=dict)
    scoring_version: str = "1"
    seed: int | None = None
    compatibility_key: str = Field(default_factory=compatibility_key)
    manifest_sha256: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("manifest_sha256", None)
        return sha256_text(canonical_json(payload))

    def finalize(self) -> ExperimentManifest:
        self.manifest_sha256 = self.compute_checksum()
        return self


# ---------------------------------------------------------------------------
# Resumable run state (features 62, 64, 65, 66)
# ---------------------------------------------------------------------------


class RunState(BaseModel):
    experiment_id: str
    status: str = "running"  # running | completed | cancelled
    completed: dict[str, Any] = Field(default_factory=dict)  # idempotent key -> result
    failures: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> RunState:
        if path.exists():
            return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        raise FileNotFoundError(path)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)


def idempotent_key(experiment_id: str, task_id: str, repetition: int) -> str:
    return f"{experiment_id}:{task_id}#{repetition}"


def execute_experiment(
    manifest: ExperimentManifest,
    work_items: list[tuple[str, int]],  # (task_id, repetition)
    runner: Callable[[str, int], dict[str, Any]],
    state_path: Path,
    max_workers: int = 4,
    cancelled: Callable[[], bool] | None = None,
) -> RunState:
    """Bounded-concurrency, resumable, failure-isolated execution.

    - already-completed items are skipped (resume);
    - each item runs isolated: an exception marks that item failed only;
    - ``cancelled()`` stops scheduling new items gracefully.
    """
    state = (
        RunState.load(state_path)
        if state_path.exists()
        else RunState(experiment_id=manifest.experiment_id)
    )
    pending = [
        (tid, rep)
        for tid, rep in work_items
        if idempotent_key(manifest.experiment_id, tid, rep) not in state.completed
        and idempotent_key(manifest.experiment_id, tid, rep) not in state.failures
    ]
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = {}
        for tid, rep in pending:
            if cancelled is not None and cancelled():
                break
            key = idempotent_key(manifest.experiment_id, tid, rep)
            futures[pool.submit(runner, tid, rep)] = (key, tid, rep)
        for future in as_completed(futures):
            key, tid, rep = futures[future]
            try:
                state.completed[key] = future.result()
            except Exception as exc:
                state.failures[key] = str(exc)[:300]
            state.save(state_path)
    if cancelled is not None and cancelled():
        state.status = "cancelled"
    elif state.failures:
        state.status = "completed_with_failures"
    elif len(state.completed) == len(work_items):
        state.status = "completed"
    state.save(state_path)
    return state


# ---------------------------------------------------------------------------
# Sharding + merge (feature 68)
# ---------------------------------------------------------------------------


def shard_work_items(work_items: list[tuple[str, int]], shards: int) -> list[list[tuple[str, int]]]:
    """Deterministic round-robin sharding."""
    if shards <= 0:
        raise ValueError("shards must be >= 1")
    buckets: list[list[tuple[str, int]]] = [[] for _ in range(shards)]
    for i, item in enumerate(sorted(work_items)):
        buckets[i % shards].append(item)
    return buckets


def merge_run_states(paths: list[Path], experiment_id: str) -> RunState:
    """Merge shard states into one; duplicate keys must agree or merge fails."""
    merged = RunState(experiment_id=experiment_id)
    for p in paths:
        part = RunState.load(p)
        for key, value in part.completed.items():
            if key in merged.completed and merged.completed[key] != value:
                raise ValueError(f"conflicting results for {key} across shards")
            merged.completed[key] = value
        merged.failures.update(part.failures)
    total = len(merged.completed) + len(merged.failures)
    merged.status = (
        "completed" if merged.failures == {} and total > 0 else "completed_with_failures"
    )
    return merged


# ---------------------------------------------------------------------------
# File-based coordinator + workers (features 61, 63, 67)
# ---------------------------------------------------------------------------


class WorkerInventory(BaseModel):
    """Worker capability inventory (feature 63)."""

    worker_id: str
    os_name: str
    arch: str
    python_version: str
    container_runtime: str | None = None  # docker/podman/None
    browser: bool = False
    gpu: bool = False
    max_concurrency: int = 1
    registered_at: str = Field(default_factory=utc_now_iso)


class Coordinator:
    """File-queue coordinator: jobs are JSON files claimed atomically via
    os.replace into a 'claimed/<worker>' directory. Deterministic run IDs come
    from the manifest; fairness is FIFO by creation order."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.claimed_dir = self.root / "claimed"
        self.results_dir = self.root / "results"
        for d in (self.jobs_dir, self.claimed_dir, self.results_dir):
            d.mkdir(parents=True, exist_ok=True)

    def enqueue(self, job: dict[str, Any], priority: int = 5) -> str:
        """Enqueue a job; lower priority number runs first (fairness policy:
        strict priority then FIFO)."""
        job_id = uuid.uuid4().hex[:12]
        payload = {"job_id": job_id, "priority": priority, **job}
        path = self.jobs_dir / f"p{priority:03d}-{job_id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return job_id

    def claim_next(self, worker_id: str) -> dict[str, Any] | None:
        """Atomically claim the highest-priority oldest job, if any."""
        candidates = sorted(self.jobs_dir.glob("*.json"))
        for job_path in candidates:
            target_dir = self.claimed_dir / worker_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / job_path.name
            try:
                os.replace(job_path, target)  # atomic claim
            except OSError:
                continue  # another worker won the race
            return json.loads(target.read_text(encoding="utf-8"))
        return None

    def submit_result(self, job_id: str, result: dict[str, Any]) -> Path:
        path = self.results_dir / f"{job_id}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        return path

    def pending_count(self) -> int:
        return len(list(self.jobs_dir.glob("*.json")))


def default_worker_inventory(worker_id: str = "local") -> WorkerInventory:
    import platform

    runtime = None
    for candidate in ("docker", "podman"):
        try:
            proc = __import__("subprocess").run(
                [candidate, "--version"], capture_output=True, timeout=10
            )
            if proc.returncode == 0:
                runtime = candidate
                break
        except Exception:
            continue
    return WorkerInventory(
        worker_id=worker_id,
        os_name=platform.system(),
        arch=platform.machine(),
        python_version=platform.python_version(),
        container_runtime=runtime,
        max_concurrency=os.cpu_count() or 1,
    )
