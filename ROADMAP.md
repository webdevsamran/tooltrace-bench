# Roadmap

Statuses: ✅ shipped · 🚧 in progress · 📋 planned. This file is synchronized with reality; items are only marked ✅ when the code and tests exist.

## v0.1 — Foundation (current)

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
      deterministic sample evaluations, security checks, frontend pipeline

## v0.2 — Breadth

- 📋 More task packs: concurrency, streaming, long-horizon refactors
- 📋 Additional sandbox providers (e.g. Firecracker/microVM) behind extras
- 📋 Statistical significance helpers for A/B agent comparisons
- 📋 Trace diffing UI improvements (side-by-side run comparison)
- 📋 Windows/macOS CI matrix hardening

## v0.3 — Ecosystem

- 📋 Community task-pack registry conventions (no central hosting required)
- 📋 Reproduction service conventions for third-party verifiers
- 📋 Optional model-judge harness with recorded judge configuration

## Future (optional, non-OSS-blocking)

Enterprise concepts — private result storage, organization dashboards, worker
fleets, SSO/RBAC, audit logs, support — are documented as *future optional*
concepts only. The community/core edition remains fully useful and open; nothing
above is crippled to sell these.