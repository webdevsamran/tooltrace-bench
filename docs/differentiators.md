# Differentiators

Why ToolTrace Bench exists and what makes it different. These are commitments,
not marketing: each item names the code that delivers it.

## 1. Trajectory reliability is first-class, not a side effect

Coding benchmarks grade the final patch. Observability platforms store traces
but never score them against assertions. ToolTrace Bench scores **the whole
trajectory**: outcome correctness (`scoring/composite.py`), tool behavior
(`tools/executor.py` stats), forbidden-side-effect detection
(`tooltrace/metrics/policy.py`), change minimality, verification quality, loop
detection and policy compliance — every one a deterministic, testable metric.

## 2. Recovery is measured, not assumed

`tooltrace perturb` injects controlled faults (tool failures, moved files,
malformed API responses, delays) and measures whether agents recover **without
unsafe repeated side effects** (`tooltrace/perturbations/`, `tooltrace/analysis/failures.py`,
chaos suites). No other open benchmark harness ships fault injection as a
core primitive.

## 3. Reproducibility you can verify, not just claim

Every run produces a `.tooltrace` bundle with SHA-256 checksums over task,
trace, diff, scoring and environment manifests; `tooltrace reproduce`
re-verifies hashes and re-runs deterministically (`bundles.py`,
`bundles_repro.py`). Tamper-evidence extends to signed bundles and
invalidation/supersession records — results found flawed are marked, never
silently deleted.

## 4. Judge-free, not judge-optional

Scoring is deterministic code. All fifteen registered scorers read the final
workspace or a produced artifact and return a number a second run reproduces
exactly; `tooltrace/scoring/` imports nothing that reaches a network. There is
no model in the scoring loop, which is why a score here can be recomputed by a
third party from the bundle alone.

The type system reserves a place for a judge — `EvalResult.judge_config`,
`ScoringContract.judge_required` in `tooltrace/tasks/v2.py`, and a
`judge_not_needed` lint in `tooltrace/tasks/linting.py` — so a future adapter
can declare its dependency rather than hide it. **No judge adapter ships
today**, and `docs/feature-status.md` grades rows 45 and 46 `D` (declared only)
for exactly that reason.

> **Correction, 2026-09-09.** This section previously claimed that judge
> disagreement was reported rather than averaged and that calibration datasets
> measured drift, citing `scoring/judges.py` — a module that has never existed.
> Three further citations in this file (`metrics/sideeffects.py`,
> `metrics/recovery.py`, `perturbations.py`) were stale renames.
> `scripts/check_doc_code_refs.py` now checks every document, not just
> `docs/feature-status.md`.

## 5. Local-first, offline-capable, vendor-neutral

One pip install runs everything offline: scripted agents for CI, local
sandboxes, generic protocol adapters for any OpenAI-/Anthropic-/Gemini-
compatible endpoint including local servers. No account, no telemetry, no
cloud dependency. Enterprise layers add scale — they never gate individual
functionality.

## 6. Cohort safety as a hard rule

Results from different task-protocol/trace/result schema versions can never be
compared or ranked together (`compatibility_key()` gates compare/regression/
leaderboards). Public datasets carry versioned indexes so downstream consumers
inherit the same guarantees.

## 7. Unique combinations (not copies)

Several capabilities exist only as combinations here:
- **Fault-injected dual-control tasks with deterministic user simulators**
  (τ²-style semantics without LLM-simulator nondeterminism).
- **Recovery-weighted regression gates** (CI fails if recovery rate drops,
  not just success rate).
- **Contamination-flagged provenance-tracked packs with fingerprint dedup**
  across pack versions.
- **Reproducibility-scored leaderboards** (a cohort's score carries its own
  metadata-completeness measure).