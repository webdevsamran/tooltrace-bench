# Competitive Analysis

Last refreshed: 2026-08-23. Every row below was verified against the official
GitHub repository / documentation at refresh time (evidence links inline).
This file is the human-readable companion to `data/competitive-capabilities.json`
(the machine-readable capability matrix) and `product-gaps.md` (the gap list
derived from it).

Method: repository metadata fetched via the GitHub API on the refresh date;
feature claims are taken only from each project's own README/docs/releases.
We never claim a competitor lacks a feature without checking its docs; where we
could not verify a feature we mark it "unverified" rather than asserting absence.

## Landscape summary

| Project | License | Activity (pushed) | Stars | Category |
|---|---|---|---|---|
| SWE-bench | MIT | 2026-08-18 | ~5.7k | Patch-only coding benchmark |
| SWE-bench-Live (Microsoft) | MIT | 2026-08-20 | ~224 | Contamination-resistant coding benchmark |
| Terminal-Bench (Harbor/Laude) | Apache-2.0 | 2026-07-11 | ~2.6k | Terminal/OS agent benchmark |
| τ-bench (Sierra) | MIT | 2026-03-18 | ~1.4k | Tool-agent customer-service benchmark |
| τ²-bench (Sierra) | MIT | 2026-08-18 | ~1.9k | Dual-control tool-agent benchmark |
| AgentBench (THUDM) | Apache-2.0 | 2026-02-08 | ~3.7k | Multi-domain agent benchmark |
| VisualAgentBench (THUDM) | Apache-2.0 | 2025-04-24 | ~274 | Multimodal/GUI agent benchmark |
| OSWorld (xlang-ai) | Apache-2.0 | 2026-08-21 | ~3.1k | Real-desktop OS agent benchmark |
| WebArena | Apache-2.0 | 2025-11-26 | ~1.6k | Web-agent benchmark (self-hosted sites) |
| browser-use | MIT | 2026-08-22 | ~110k | Browser automation library/framework |
| inspect_ai (UK AISI) | MIT | 2026-08-23 | ~2.6k | Evaluation framework |
| promptfoo | MIT | 2026-08-23 | ~24k | LLM eval/red-teaming framework |
| DeepEval (Confident AI) | Apache-2.0 | 2026-08-21 | ~17.8k | LLM eval framework |
| ragas (VibrantLabs) | Apache-2.0 | 2026-02-24 | ~15.4k | RAG evaluation framework |
| AgentOps | MIT | 2026-06-25 | ~5.8k | Agent observability SDK |
| Arize Phoenix | mixed (ELv2-style components) | 2026-08-22 | ~11.1k | Observability/eval platform |
| Langfuse | mixed (core MIT, enterprise features commercial) | 2026-08-23 | ~33.6k | LLM observability platform |
| OpenAI Evals | custom (NOASSERTION) | 2026-04-14 | ~19.2k | Vendor eval harness |

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