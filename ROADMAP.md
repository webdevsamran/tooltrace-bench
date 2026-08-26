# Roadmap

Statuses: ✅ shipped · 🚧 in progress · 📋 planned. This file is synchronized with reality; items are only marked ✅ when the code and tests exist.

## v0.1 — Foundation (shipped)

- ✅ Versioned task spec (YAML/JSON) with formal JSON-Schema validation
- ✅ Agent adapter API with plugin discovery (`tooltrace.agents`)
- ✅ Subprocess, OpenAI-compatible (local endpoints) and scripted agents
- ✅ Ten typed tools with sanitized event emission
- ✅ Temp-workspace sandbox + optional Docker sandbox
- ✅ Versioned JSONL trace format + deterministic replay of tool interactions
- ✅ Deterministic scorers + weighted composite scoring
- ✅ Failure taxonomy (12 machine-readable categories)
- ✅ Repeated runs (`benchmark --runs N`) + reliability metrics
- ✅ Controlled perturbations (7 kinds)
- ✅ Long-context / multi-turn workloads
- ✅ `compare`, `showdown`, `baseline`, `regression` with CI thresholds + stable exit codes
- ✅ Task authoring SDK (`task scaffold/validate/test`)
- ✅ Secret sanitization + publication checks + trust states
- ✅ `.tooltrace` result bundles + `reproduce`
- ✅ CLI: doctor, agents, tasks, run, benchmark, showdown, compare, baseline,
      regression, validate, reproduce, report, export, serve
- ✅ Reports: JSON, CSV, Markdown, JUnit, standalone HTML
- ✅ React + TypeScript + Vite frontend with static JSON indexes (GitHub Pages)
- ✅ CI: lint, format, type check, pytest + coverage, build, schema/task validation,
      deterministic sample evaluations, security checks, docs link check, frontend pipeline

## v0.2 — Reliability platform (shipped 2026-08)

- ✅ Task protocol v2: domains, seeds, side effects, scoring contracts, HITL /
  dual-control / multi-agent / checkpoint stages, contamination metadata,
  provenance manifests, pack indexes, fingerprint dedup, migration from v1
- ✅ Metrics: pass@k / pass^k + confidence intervals; trajectory efficiency;
  recovery vs agent-caused failures; policy compliance; side-effect correctness;
  change minimality; verification quality; loop detection; hallucinated-resource
  metrics; context retention; abstention calibration; dual outcome/trajectory scoring
- ✅ Adapters: capability negotiation, provider metadata normalization,
  OpenAI-/Anthropic-/Gemini-compatible layers, MCP client + server conformance
  fixtures, recorded retries/backoff, doctor checks, price-table cost accounting
- ✅ Execution: experiment manifests, bounded concurrency, resumable runs,
  failure isolation, sharding/merge, worker inventory, coordinator queue
- ✅ Analysis: cohort-safe comparisons, baselines at four levels, trends with
  composition warnings, paired-run analysis, effect sizes, bootstrap/Bayesian
  extras, failure clustering, root-cause drill-down, anti-gaming checks
- ✅ Infra: Podman + Windows-native sandbox interfaces, k8s job runner backend,
  network policy profiles, deterministic clock, fault injection, harness self-test
- ✅ CLI additions: `lint`, `dry-run`, `self-test`, `snapshot`, `server`,
      `perturb`, `trace`, `benchmark --context-sweep`
- ✅ Self-hosted server: workspaces/RBAC/tokens/policy-as-code/approvals/
  audit chain/quotas/signed webhooks/retention/REST+SSE/Prometheus/OpenAPI
- ✅ Frontend: public analysis console + full team console (experiments,
  workers, studio, review queue, users, policies, audit, webhooks, health),
  charts, virtualized Trace Explorer, e2e + axe accessibility gates

## v0.3 — Ecosystem (planned)

- 📋 Community task-pack registry conventions (no central hosting required)
- 📋 Reproduction service conventions for third-party verifiers
- 📋 Judge calibration dataset publishing workflow
- 📋 Additional domain packs: concurrency, streaming, browser fixtures expansion

## Future (optional, non-OSS-blocking)

Managed/cloud deployment remains documented-but-unbuilt by design. Enterprise
concepts ship as open code in the self-hosted server; nothing in the community
edition is crippled. Compliance certifications are organizational processes and
are never claimed.
