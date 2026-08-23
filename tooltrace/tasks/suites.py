"""Benchmark suite manifests and sampling policies (features 29, 30).

Suites group tasks by domain/difficulty/resource class/protocol version.
Sampling policies produce fully recorded selection manifests so any subset is
reproducible.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from tooltrace.core.versions import TASK_PROTOCOL_VERSION, compatibility_key
from tooltrace.tasks.governance import canonical_json, sha256_text, utc_now_iso

SamplingPolicyName = Literal["fixed", "stratified", "seeded_random"]


class SuiteManifest(BaseModel):
    schema_version: int = 1
    suite_id: str
    suite_version: str = "1.0.0"
    protocol_version: int = TASK_PROTOCOL_VERSION
    description: str = ""
    task_ids: list[str] = Field(default_factory=list)
    domains: dict[str, int] = Field(default_factory=dict)  # domain -> count
    difficulties: dict[str, int] = Field(default_factory=dict)
    resource_class: str = "local"  # local | container | vm
    suite_sha256: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("suite_sha256", None)
        return sha256_text(canonical_json(payload))


def build_suite(
    suite_id: str,
    tasks: list[Any],
    resource_class: str = "local",
    description: str = "",
    suite_version: str = "1.0.0",
) -> SuiteManifest:
    domains: dict[str, int] = defaultdict(int)
    difficulties: dict[str, int] = defaultdict(int)
    ids: list[str] = []
    for t in sorted(tasks, key=lambda x: str(x.id)):
        ids.append(str(t.id))
        dom = getattr(getattr(t, "domain", None), "value", None) or str(
            getattr(t, "category", "workflow")
        )
        domains[dom] += 1
        diff = getattr(getattr(t, "difficulty", None), "value", None) or "medium"
        difficulties[diff] += 1
    suite = SuiteManifest(
        suite_id=suite_id,
        suite_version=suite_version,
        description=description,
        task_ids=ids,
        domains=dict(domains),
        difficulties=dict(difficulties),
        resource_class=resource_class,
    )
    suite.suite_sha256 = suite.compute_checksum()
    return suite


class SelectionManifest(BaseModel):
    """Fully recorded subset selection: reproducible given (policy, seed, suite)."""

    schema_version: int = 1
    suite_id: str
    suite_sha256: str
    policy: SamplingPolicyName
    seed: int | None = None
    requested: int | None = None
    selected_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    compatibility_key: str = Field(default_factory=compatibility_key)
    selection_sha256: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("selection_sha256", None)
        return sha256_text(canonical_json(payload))


def sample_suite(
    suite: SuiteManifest,
    tasks_by_id: dict[str, Any],
    policy: SamplingPolicyName = "fixed",
    n: int | None = None,
    seed: int | None = None,
    stratify_by: str = "domain",
) -> SelectionManifest:
    """Select a subset of the suite.

    - fixed: the whole suite (n must be None or equal to size).
    - seeded_random: uniform random n tasks with the given seed.
    - stratified: n per stratum (or proportional when n < strata*per), where the
      stratum key is ``domain`` or ``difficulty`` read from the task objects.
    """
    pool = [tasks_by_id[tid] for tid in suite.task_ids if tid in tasks_by_id]
    selected: list[Any]
    eff_seed = seed if seed is not None else 0

    if policy == "fixed":
        selected = pool
    elif policy == "seeded_random":
        if n is None:
            raise ValueError("seeded_random requires n")
        rng = random.Random(eff_seed)
        selected = rng.sample(sorted(pool, key=lambda t: str(t.id)), min(n, len(pool)))
    elif policy == "stratified":
        if n is None:
            raise ValueError("stratified requires n (per stratum)")
        strata: dict[str, list[Any]] = defaultdict(list)
        for t in pool:
            if stratify_by == "difficulty":
                key = str(getattr(getattr(t, "difficulty", None), "value", "medium"))
            else:
                key = str(
                    getattr(getattr(t, "domain", None), "value", None)
                    or getattr(t, "category", "workflow")
                )
            strata[key].append(t)
        rng = random.Random(eff_seed)
        selected = []
        for key in sorted(strata):
            members = sorted(strata[key], key=lambda t: str(t.id))
            take = members if len(members) <= n else rng.sample(members, n)
            selected.extend(take)
    else:  # pragma: no cover - Literal guards this
        raise ValueError(f"unknown policy: {policy}")

    sel = SelectionManifest(
        suite_id=suite.suite_id,
        suite_sha256=suite.suite_sha256,
        policy=policy,
        seed=eff_seed if policy != "fixed" else None,
        requested=n,
        selected_ids=sorted(str(t.id) for t in selected),
    )
    sel.selection_sha256 = sel.compute_checksum()
    return sel
