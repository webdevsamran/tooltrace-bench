# PRODUCT_GAPS

Generated from `docs/competitive-analysis.md` + `data/competitive-capabilities.json`
(refreshed 2026-08-23). This file lists gaps worth closing, gaps deliberately
NOT closed, and the evidence basis. Refresh only from verified evidence.

## Gaps this release closes (mapped to implementation)

| # | Gap | Evidence source | Closed by |
|---|---|---|---|
| 1 | Contamination-aware task metadata (SWE-bench-Live proved demand) | swe-bench-live | Task protocol v2 `contamination` field + docs |
| 2 | Dual-control world-state evaluation without an LLM user simulator | tau2-bench | Deterministic dual-control task interface |
| 3 | Human-in-the-loop states modeled explicitly | tau2-bench / industry direction | HITL task states with approval gates |
| 4 | pass@k / pass^k reliability statistics in the core harness | inspect_ai has them; most benchmarks don't | `tooltrace.stats` v2 metrics module |
| 5 | CI regression gating for agent reliability (not just prompt evals) | promptfoo/DeepEval do prompts; nobody does trajectories | `tooltrace regression` multi-level baselines |
| 6 | Cost accounting from explicit price tables (no hidden assumptions) | langfuse/promptfoo have pricing; benchmark harnesses don't | Price-table cost module with timestamped metadata |
| 7 | MCP-era tool ecosystems need conformance testing | industry direction (MCP adoption) | MCP client adapter + server conformance fixtures |
| 8 | Self-hosted team collaboration is paywalled elsewhere | langfuse/phoenix enterprise tiers | Open-source team server: RBAC, policy, audit |
| 9 | Signed/tamper-evident result artifacts | unverified anywhere → trust gap | Bundle signing + checksum manifests |
| 10 | Cohort-safe leaderboards (never rank incompatible versions) | all public leaderboards mix cohorts implicitly | Version-gated leaderboard generation |

## Gaps deliberately NOT closed

1. **Hosted submission queues** (SWE-bench style) — we publish versioned
   datasets; running a hosted service is out of scope for an OSS repo.
2. **Cloned production websites as eval targets** (WebArena style) — legal and
   operational burden; our local deterministic web fixtures serve CI use cases.
3. **Always-on cloud telemetry** — anti-goal; zero telemetry by default.
4. **Real-desktop VM farms** (OSWorld style) — valuable but not CI-compatible;
   we provide deterministic desktop abstractions instead.
5. **Proprietary gating of security features** — anti-pattern we refuse.

## Evidence discipline

- Every "competitor lacks X" claim above traces to a checked doc/release on
  2026-08-23; anything unchecked is marked `unverified` in the JSON matrix.
- This file must never contain claims about competitors that are not backed by
  the JSON matrix or the analysis doc.