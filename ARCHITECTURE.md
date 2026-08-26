# Architecture

This document describes how ToolTrace Bench is designed, why, and where each responsibility lives. It is kept in sync with the code; if it drifts, that is a bug.

## Design principles

1. **Vendor-neutral core.** The evaluation engine never depends on any model provider. Remote providers are optional adapters; local/offline operation is the default.
2. **Determinism first.** Tasks, fixtures, scorers and the scripted agent are deterministic. Model-in-the-loop runs are supported but never required.
3. **Everything is a trace.** Every tool request/result, diff, validation and retry is recorded in a versioned JSONL trace. Traces are first-class artifacts, not logs.
4. **Deterministic scoring.** Scores come from executable checks (tests, file/AST/JSON-schema checks, exit codes, git constraints, API state, data equality). Optional model judges are recorded separately and never mixed into the deterministic score.
5. **Honest isolation.** The default sandbox isolates the workspace filesystem and disables network access at the tool layer. Stronger guarantees (network namespaces, cgroups) require Docker and are documented honestly in `docs/threat-model.md`.
6. **Separate versioning.** Framework version, result-schema version, task-protocol version and per-task-definition versions evolve independently. Comparisons refuse mismatched protocol versions.

## Module map

```
tooltrace/
├── core/          Data models (TaskDefinition, ToolCall, TraceEvent, EvalResult,
│                  Score, FailureReason, BenchmarkRun, RegressionReport),
│                  registries and plugin discovery.
├── cli/           Command-line application: doctor, agents, tasks, run, benchmark,
│                  showdown, compare, baseline, regression, validate, lint,
│                  dry-run, self-test, snapshot, perturb, trace, reproduce,
│                  report, export, serve.
├── tasks/         YAML loading + JSON-Schema validation, task SDK
│                  (scaffold / validate / test), protocol v2, governance,
│                  linting, suites, bundled packs under packs/.
├── agents/        AgentAdapter ABC + subprocess, openai_compat, scripted,
│                  provider-interop layers (OpenAI/Anthropic/Gemini-compatible)
│                  and MCP client.
├── tools/         Typed tools: read_file, write_file, patch_file, list_directory,
│                  search_text, shell, git, calculator, test_runner, http.
│                  Every call emits a sanitized ToolEvent.
├── sandbox/       TempWorkspaceSandbox (default), DockerSandbox (optional),
│                  infra providers (Podman / Windows-native / k8s job runner),
│                  workspace boundary enforcement, env allowlist, network
│                  policy profiles, timeouts, cleanup.
├── scoring/       Deterministic scorer registry + weighted composite scoring.
├── runners/       Single-run runner and repeated-run benchmark runner
│                  (incl. long-context sweeps).
├── executors/     Experiment manifests, bounded concurrency, resumable runs,
│                  sharding/merge, worker inventory, coordinator queue.
├── perturbations/ Controlled fault injection: transient tool failure, non-zero
│                  command exit, moved file, mock-API error, delay, ambiguous
│                  error, irrelevant files.
├── artifacts/     `.tooltrace` bundles: SHA-256 checksum manifests, signed
│                  bundles, deterministic reproduction, partial replay.
├── analysis/      Cohort-safe comparisons (`compare`), regression checks,
│                  baselines/trends/snapshots (`core`), failure classification
│                  (`failures`) and reliability statistics incl. pass@k/pass^k
│                  and Wilson intervals (`stats`).
├── metrics/       Trajectory efficiency, policy compliance, side-effect and
│                  recovery/reliability metrics.
├── telemetry/     Wall/model/tool timers, token usage (when available), cost
│                  (only when a provider reports it), OTel/Prometheus exporters.
├── reports/       JSON, CSV, Markdown, JUnit and standalone HTML report
│                  generation; exporters/ holds the reporter plugin API.
├── security/      Secret sanitization, publication checks, trust states.
└── server/        Self-hosted team server: workspaces/RBAC/tokens/policy-as-code/
                   approvals/audit chain/quotas/signed webhooks/retention,
                   REST+SSE+Prometheus/OpenAPI.
```

Deprecated import shims (`tooltrace/bundles.py`, `bundles_repro.py`, `stats.py`,
`compare.py`, `failures.py`) keep pre-0.2 plugin imports working; they re-export
from `artifacts.*` / `analysis.*` and will be removed no earlier than v0.4.

## Run lifecycle

```
1. Load & validate TaskDefinition (schemas/task.schema.json)
2. Create sandbox; materialize starting workspace + fixtures
3. Snapshot workspace (for diffing)
4. Initialize AgentAdapter with task context + allowed tools
5. Loop until finish/max_steps/timeout:
     agent action ──► policy check (allowed tool? boundary? network?)
                  ──► execute tool ──► sanitized ToolEvent ──► observation to agent
6. Compute workspace.diff against snapshot
7. Run deterministic assertions → Score
8. Classify FailureReason from trace heuristics
9. Assemble EvalResult + .tooltrace bundle (checksums included)
```

## Trace format (v1)

JSONL, one event per line: `task_start`, `agent_message`, `tool_request`, `tool_result`, `workspace_diff`, `validation`, `retry_recovery`, `task_end`. Each event carries an ISO-8601 timestamp, a monotonic sequence number and a typed payload. Non-model tool interactions can be replayed deterministically by `tooltrace.replay`.

## Scoring

Each assertion type maps to a registered scorer returning 0..1. The composite score is the weighted mean of component scores using the task's declared weights. A run "succeeds" only if every assertion scores 1.0; partial success means total ≥ 0.5 with at least one failing component.

## Reliability metrics

Computed over repeated runs (`benchmark --runs N`): success rate, partial-success rate, mean/median steps and tool calls, failed-tool-call rate, recovery rate (successful completions after injected faults), invalid/hallucinated tool-use count, repeated-call rate, unnecessary-change count, workspace violations, test-pass ratio, wall/model/tool latency (p50/p95), token usage when available, provider-reported cost only, and consistency with Wilson confidence intervals.

## Extension points

Entry-point groups (see `pyproject.toml`): `tooltrace.agents`, `tooltrace.tools`, `tooltrace.task_packs`, `tooltrace.scorers`, `tooltrace.reporters`, `tooltrace.sandboxes`. Contributors add task packs, adapters, scorers or sandbox providers without touching core internals.

## Frontend data flow

`tooltrace export --web` scans validated bundles under `results/` and emits static JSON indexes consumed by the React app. No backend is mandatory; GitHub Pages serves the built app.