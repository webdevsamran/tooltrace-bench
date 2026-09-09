# Competitive Analysis

Repository facts in this file are generated, not typed. The snapshot below is
rendered from `data/competitor-meta.json` by `scripts/generate_landscape.py`,
which CI re-checks on every run, and it carries its own fetch date -- so there
is no separate "last refreshed" line to go stale.

Method: repository metadata comes from the GitHub API on the recorded date.
Feature claims are taken only from each project's own README, docs or releases.
We never claim a competitor lacks a feature without checking its docs; where we
could not verify a feature it is marked "unverified" rather than asserted as
missing.

> **Correction, 2026-09-09.** This file previously carried a hand-written
> "Landscape summary" table dated 2026-08-23 twenty lines below the generated
> one, and the two disagreed: SWE-bench was listed as pushed 2026-08-18 against
> the generated 2026-09-02, and SWE-bench-Live as ~224 stars against 234. Three
> of its eighteen projects were never fetched at all, and two of those had moved
> org. The hand table is deleted; every fact now comes from the fetch, and a
> test rejects any star-bearing table outside the generated markers so it cannot
> return.


<!-- landscape:generated -->
## Landscape snapshot (fetched 2026-09-09)

| Project | Category | License | Stars | Last push | Latest release | Status |
|---|---|---|---|---|---|---|
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | Browser automation library | MIT | 113,915 | 2026-09-07 | 0.13.10 (2026-09-04) | active |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | LLM observability platform | NOASSERTION | 34,402 | 2026-09-09 | v4.32.0 (2026-09-08) | active |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | LLM eval and red-teaming framework | MIT | 24,972 | 2026-09-09 | code-scan-action-0.2.0 (2026-08-28) | active |
| [openai/evals](https://github.com/openai/evals) | Vendor eval harness | NOASSERTION | 19,417 | 2026-04-14 | — | active |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | LLM evaluation framework | Apache-2.0 | 18,189 | 2026-09-08 | python-v4.2.0 (2026-08-24) | active |
| [vibrantlabsai/ragas](https://github.com/vibrantlabsai/ragas)<br><sub>moved from explodinggradients/ragas</sub> | RAG evaluation framework | Apache-2.0 | 15,691 | 2026-02-24 | v0.4.3 (2026-01-13) | active |
| [ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla) | Function-call benchmark + leaderboard (BFCL) | Apache-2.0 | 13,018 | 2026-04-13 | v1.3 (2025-07-17) | active |
| [Arize-ai/phoenix](https://github.com/Arize-ai/phoenix) | Observability and eval platform | NOASSERTION | 11,389 | 2026-09-09 | arize-phoenix-client-v3.5.0 (2026-09-08) | active |
| [AgentOps-AI/agentops](https://github.com/AgentOps-AI/agentops) | Agent observability SDK | MIT | 5,813 | 2026-06-25 | 0.4.21 (2025-08-29) | active |
| [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench) | Patch-only coding benchmark | MIT | 5,808 | 2026-09-02 | — | active |
| [OpenBMB/ToolBench](https://github.com/OpenBMB/ToolBench) | Static tool/API catalog benchmark | Apache-2.0 | 5,736 | 2025-05-21 | — | active |
| [THUDM/AgentBench](https://github.com/THUDM/AgentBench) | Multi-domain agent benchmark | Apache-2.0 | 3,718 | 2026-02-08 | — | active |
| [xlang-ai/OSWorld](https://github.com/xlang-ai/OSWorld) | Real-desktop OS agent benchmark | Apache-2.0 | 3,134 | 2026-08-30 | v0.1.16 (2024-06-26) | active |
| [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) | Evaluation framework | MIT | 2,735 | 2026-09-09 | — | active |
| [harbor-framework/terminal-bench-1](https://github.com/harbor-framework/terminal-bench-1)<br><sub>moved from laude-institute/terminal-bench</sub> | Terminal/OS agent benchmark | Apache-2.0 | 2,572 | 2026-07-11 | — | active |
| [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench) | Dual-control tool-agent benchmark | MIT | 1,994 | 2026-09-07 | v1.0.1 (2026-07-22) | active |
| [mlcommons/inference](https://github.com/mlcommons/inference) | Serving-scale inference benchmark | Apache-2.0 | 1,624 | 2026-09-02 | v5.1.1 (2025-10-28) | active |
| [web-arena-x/webarena](https://github.com/web-arena-x/webarena) | Web-agent benchmark (self-hosted sites) | Apache-2.0 | 1,606 | 2025-11-26 | v0.2.0 (2023-10-21) | active |
| [sierra-research/tau-bench](https://github.com/sierra-research/tau-bench) | Tool-agent customer-service benchmark | MIT | 1,427 | 2026-03-18 | — | active |
| [ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo) | Prompt-injection security benchmark | MIT | 810 | 2026-06-02 | v0.1.35 (2025-10-27) | active |
| [UKGovernmentBEIS/inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals) | Evaluation suite for inspect_ai | MIT | 664 | 2026-09-09 | v0.19.0 (2026-08-31) | active |
| [THUDM/VisualAgentBench](https://github.com/THUDM/VisualAgentBench) | Multimodal/GUI agent benchmark | Apache-2.0 | 276 | 2025-04-24 | — | active |
| [microsoft/SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live) | Contamination-resistant coding benchmark | MIT | 234 | 2026-09-07 | v1.0-multi-language-multi-os-benchmarking (2026-03-08) | active |
| [uiuc-kang-lab/InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) | Prompt-injection security benchmark | MIT | 168 | 2024-07-02 | — | active |
| [microsoft/BIPIA](https://github.com/microsoft/BIPIA) | Indirect prompt-injection benchmark | NOASSERTION | 157 | 2024-04-15 | — | active |
| [mlcommons/mlperf_client](https://github.com/mlcommons/mlperf_client) | Vendor-curated PC hardware benchmark | Apache-2.0 | 90 | 2026-08-18 | v2.0 (2026-08-18) | active |

Rows are generated from `data/competitor-meta.json` by `scripts/fetch_competitor_meta.py`, which reads the GitHub API. Star counts and dates are facts about the repositories on the fetch date, not judgements. Nothing here claims a project lacks a feature: where a capability was not verified it is absent from this table rather than asserted as missing. **Category** is the one column the API cannot supply: it is a labelled human judgement kept in `data/competitor-registry.json`, which is also the single list of what gets fetched.
<!-- /landscape:generated -->

## Per-competitor detail

### SWE-bench / SWE-bench-Live — patch-only coding benchmarks
- Evidence: https://github.com/SWE-bench/SWE-bench (MIT), https://github.com/microsoft/SWE-bench-Live (MIT)
- Target audience: coding-model researchers and leaderboard maintainers.
- Deployment model: local harness + hosted leaderboard/submission queues.
- Coverage: repository-level bug fixing judged by hidden tests (FAIL_TO_PASS /
  PASS_TO_PASS). SWE-bench-Live adds continuously refreshed tasks to resist
  training-data contamination.
- Strengths: gold-standard task construction discipline; huge mindshare;
  deterministic test-based scoring.
- Weaknesses (verified from their docs): scores only the final patch — no
  trajectory, tool-behavior, recovery, cost or efficiency signal; single domain
  (Python repos for classic SWE-bench); no repeated-run reliability statistics
  in the core harness; no CI regression gate concept.
- What we do better: full-trajectory evaluation (tool calls, side effects,
  recovery), pass^k/pass@k reliability metrics, regression baselines as CI gates,
  multi-domain packs beyond code patches.
- Not worth copying: their submission-queue infrastructure (we publish versioned
  datasets instead of running a hosted leaderboard service).

### Terminal-Bench — terminal/OS agents
- Evidence: https://github.com/harbor-framework/terminal-bench-1 (Apache-2.0)
- Target audience: CLI/terminal agent builders.
- Coverage: containerized terminal tasks with verifier scripts.
- Strengths: strong sandbox isolation story; oracle verifiers; active ecosystem.
- Weaknesses: focused on terminal interaction; limited statistical reliability
  reporting; no built-in team/self-hosted collaboration layer.
- What we do better: vendor-neutral adapter model (not tied to one agent
  runtime), perturbation/fault-injection recovery measurement, trace bundles
  with reproducibility verification.
- Worth borrowing: container-verifier conventions → reflected in our Docker/
  Podman sandbox providers and conformance fixtures.

### τ-bench / τ²-bench — tool-agent + user simulation
- Evidence: https://github.com/sierra-research/tau-bench (MIT),
  https://github.com/sierra-research/tau2-bench (MIT)
- Coverage: customer-service domains (airline/retail/telecom); τ² adds
  dual-control where both user-simulator and agent mutate state, plus
  communication-quality judging via LLM judges.
- Strengths: pioneered dual-control evaluation; realistic policy documents.
- Weaknesses: narrow domain set; depends on an LLM user-simulator (non-
  deterministic by default); judge-dependent scoring for subjective parts.
- What we do better: deterministic local user simulators (scripted/dual-control
  fixtures), judge-independence reporting, calibration datasets for any
  model-based scorer, offline-first operation.
- Worth borrowing: dual-control world-state semantics → implemented in our
  dual-control task interface.

### AgentBench / VisualAgentBench — multi-domain academic benchmarks
- Evidence: https://github.com/THUDM/AgentBench (Apache-2.0),
  https://github.com/THUDM/VisualAgentBench (Apache-2.0)
- Coverage: many environments (OS, DB, web browsing, games, embodied).
- Strengths: breadth; academic rigor of task design.
- Weaknesses: heavyweight environment setup; activity has slowed (VAB last
  pushed 2025-04); complex install; not designed as a CI regression tool.
- What we do better: lightweight local-first execution, one-command runs,
  reproducible bundles, plugin API with conformance tests.

### OSWorld — real-desktop OS benchmark
- Evidence: https://github.com/xlang-ai/OSWorld (Apache-2.0)
- Coverage: Ubuntu VM desktop tasks across office apps, OS operations.
- Strengths: most realistic computer-use evaluation available open-source.
- Weaknesses: requires VM infrastructure; slow; screenshots+VM state make
  strict reproducibility hard; not CI-friendly.
- What we do better: deterministic local sandboxes with optional Docker/Podman/
  K8s backends; CI-safe GUI/desktop abstractions with mocked evidence channels.
- Worth borrowing: accessibility-tree/DOM/screenshot evidence channels →
  implemented in our desktop/GUI task interface.

### WebArena / browser-use — web agents
- Evidence: https://github.com/web-arena-x/webarena (Apache-2.0),
  https://github.com/browser-use/browser-use (MIT)
- WebArena hosts its own copies of target sites; browser-use is an automation
  library (not primarily a benchmark) with huge adoption.
- What we do better: fully local deterministic web fixture environment (no
  self-hosted clones of public sites needed), outcome assertions over local
  state rather than live-site scraping.
- Not worth copying: hosting cloned production websites.

### inspect_ai (UK AISI) — evaluation framework
- Evidence: https://github.com/UKGovernmentBEIS/inspect_ai (MIT)
- Strengths: excellent solver/task abstractions, sandbox support, scorers,
  widely used for safety evals; actively maintained.
- Weaknesses vs us: Python-framework-centric (no standalone product UI);
  reliability statistics (pass^k etc.) exist but trajectory-level failure
  taxonomy/recovery analytics and CI regression gating are not first-class;
  no bundled frontend console.
- What we do better: product surface (CLI + console UI), failure taxonomy,
  recovery/perturbation analytics, cohort-safe leaderboards, self-hosted team
  server with RBAC/policy/audit.

### promptfoo / DeepEval / ragas — LLM eval frameworks
- Evidence: https://github.com/promptfoo/promptfoo (MIT),
  https://github.com/confident-ai/deepeval (Apache-2.0),
  https://github.com/vibrantlabsai/ragas (Apache-2.0)
- Focus: prompt/model output quality, RAG metrics, red-teaming; heavy reliance
  on model judges for subjective metrics.
- What we do better: executable-environment outcomes (files, DBs, APIs, git)
  rather than text-only judgments; deterministic scoring first; tool-behavior
  and side-effect correctness; reproducibility bundles.
- Worth borrowing: assertion DSL ergonomics and CI integration patterns.

### AgentOps / Phoenix / Langfuse — observability platforms
- Evidence: https://github.com/AgentOps-AI/agentops (MIT),
  https://github.com/Arize-ai/phoenix (mixed license),
  https://github.com/langfuse/langfuse (mixed license)
- Focus: tracing/monitoring dashboards for production agents; some offline
  eval modules. Langfuse/Phoenix reserve advanced features (RBAC, SSO, audit)
  for paid tiers.
- What we do better: evaluation is the product, not a side feature; traces are
  scored against assertions; everything reproducible locally without a server;
  our team/enterprise layers are self-hostable open source.
- Not worth copying: always-on telemetry (we default to zero telemetry).

### BFCL / Gorilla — function-call correctness leaderboard

- Evidence: [ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla) (Apache-2.0). Leaderboard: <https://gorilla.cs.berkeley.edu/leaderboards.html>
- **Citation note.** BFCL's dataset generations ("v3", "v4") are versions of the
  leaderboard and its data, not of the repository: the repo's own release tags
  stop at `v1.3` (2025-07-17). A claim about a BFCL generation therefore has to
  cite the leaderboard, with the date it was read — citing a GitHub release for
  it would be citing something that does not exist.
- Coverage: whether a model emits the correct function call, matched structurally
  against an expected signature (an AST comparison) so thousands of functions can
  be graded without executing any of them. That technique is a good one and is
  worth adopting; it is not the same measurement as this project's.
- Distinction: BFCL scores **the call**, on a model leaderboard. tooltrace-bench
  scores **the run** — recovery from failure, side effects on the environment,
  cost, and whether a third party can reproduce the number from the bundle.
  Neither subsumes the other: an agent can emit every call correctly and still
  destroy the workspace, and an agent can fumble a call and recover cleanly.

### MLPerf Client / MLPerf Inference — hardware and serving benchmarks

- Evidence: [mlcommons/mlperf_client](https://github.com/mlcommons/mlperf_client) (Apache-2.0), release `v2.0` published 2026-08-18; [mlcommons/inference](https://github.com/mlcommons/inference) (Apache-2.0).
- Coverage: MLPerf Client v2.0 added an agentic category reporting end-to-end
  performance with a breakdown of model time against tool-execution time.
  MLPerf Inference covers serving-scale throughput against OpenAI-compatible
  endpoints.
- Distinction: these are vendor-curated hardware and serving benchmarks, not
  agent-reliability harnesses — and they are a validating signal rather than a
  rival. The inference-time/tool-time split they report is the same
  decomposition this project already records per run (`model_ms` and `tool_ms`
  on every `EvalResult`); what is missing here is the aggregation and the
  hardware profile to report it against, which is tracked work rather than a
  claim.

### agentdojo / InjecAgent / BIPIA — prompt-injection benchmarks

- Evidence: [ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo) (MIT), [uiuc-kang-lab/InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) (MIT), [microsoft/BIPIA](https://github.com/microsoft/BIPIA) (NOASSERTION).
- Coverage: adversarial resilience in isolation — whether an agent can be
  diverted by injected instructions.
- Activity, from the fetch above: agentdojo is active; InjecAgent was last
  pushed 2024-07-02 and BIPIA 2024-04-15. BIPIA carries no recognised licence
  (`NOASSERTION`), which is a practical constraint on reusing its corpus rather
  than a criticism of it.
- **This project does not currently measure any of this.**
  `docs/feature-status.md` row 16 (defensive-security packs) is graded `S`:
  the domain is declarable and no pack ships. Listing these projects here is
  not a claim to compete with them.

### OpenAI Evals — vendor harness
- Evidence: https://github.com/openai/evals (custom license)
- Historic importance; largely maintenance mode (last push 2026-04); tied to
  OpenAI model access patterns.
- What we do better: vendor-neutral adapters, local models supported through
  generic protocol layers.

## Capability matrix

See `data/competitive-capabilities.json` for the machine-readable matrix with
per-capability values (`yes` / `partial` / `no` / `unverified`) and evidence
links. Cohort rules: capabilities were marked `no` only after checking the
project's README/docs/release notes on the refresh date; otherwise
`unverified`.

## Strategic conclusions

1. **Nobody owns "trajectory reliability as a product."** Coding benchmarks own
   final-patch correctness; observability platforms own trace storage; eval
   frameworks own prompt quality. The intersection — deterministic outcome +
   tool behavior + recovery + efficiency + reproducibility, packaged as a
   local-first product with a CI gate — is unoccupied.
2. **Contamination resistance is table stakes** (SWE-bench-Live proved demand).
   Our provenance manifests, contamination metadata and fingerprinting address
   this honestly (flagging risk, not pretending proof).
3. **Dual-control and HITL are emerging standards** (τ²-bench). We implement
   them deterministically without requiring an LLM user simulator.
4. **Enterprise controls are paywalled elsewhere** (Langfuse/Phoenix). Ours are
   open source and self-hosted, which is a genuine differentiator — but they
   must actually work, which is why this release ships them with tests.
5. **Do not chase parity with browser-use's scale or OSWorld's realism.** Our
   deterministic local web/desktop/mobile interfaces serve CI and regression
   use cases those projects explicitly do not target.

## Features deliberately NOT copied

- Hosted submission queues / private leaderboard services (SWE-bench style).
- Clones of public websites as eval targets (WebArena style).
- Always-on cloud telemetry SDKs (observability-platform style).
- Proprietary enterprise-only gating of security features.
- Any proprietary code, assets or branding from the projects above.
