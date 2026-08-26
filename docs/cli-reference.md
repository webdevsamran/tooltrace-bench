# CLI Reference

All commands accept `--json` for structured output.

Exit codes: `0` ok · `2` usage · `3` task/validation · `4` agent · `5` run failure · `8` regression threshold · `9` secrets detected · `130` interrupted.

## Core workflow commands

| Command | Purpose |
|---|---|
| `doctor` | Environment, registries, plugin discovery health check |
| `tasks [--category]` | List bundled tasks |
| `run --task ID --agent A [--agent-config JSON] [--out DIR]` | One deterministic task against one agent; writes a bundle |
| `benchmark --agent A [--runs N] [--task ids] [--context-sweep] [--min-success-rate]` | Repeated reliability runs with pass@k/pass^k-aware summaries |
| `showdown --agents a,b [--runs N]` | Fair multi-agent ranking on identical cohorts |
| `compare --baseline B --current C [--metrics m1,m2]` | Metric-by-metric bundle comparison |
| `baseline --name N --bundle PATH` | Record a named baseline |
| `regression --baseline B --current C --thresholds JSON` | CI gate for score/tool/latency regressions |
| `reproduce BUNDLE [--out DIR] [--no-rerun]` | Verify hashes and optionally re-run |
| `perturb --task ID [--perturbation kind:tool] [--runs N] [--min-recovery-rate R]` | Inject safe faults and measure recovery rate; `--out` writes bundles |
| `trace BUNDLE [--filter SUBSTR] [--assertions] [--limit N]` | Inspect a bundle trace in the terminal (checksum-verified) |

## Reporting / export

| Command | Purpose |
|---|---|
| `report --bundles DIR... [--format json\|csv\|md\|junit\|html] [--output F]` | Aggregate bundles into a report |
| `export --out DIR [--stdin]` | Run exporter plugins on a payload |
| `serve --dir web/dist [--host] [--port]` | Serve the built frontend locally |

## Quality / safety gates

| Command | Purpose |
|---|---|
| `lint [--path PACK]` | Task-lint: ambiguous scoring, unreachable assertions, undeclared side effects, missing cleanup, unsafe network |
| `dry-run --task ID` | Validate fixtures/assertions/sandbox lifecycle without any model |
| `self-test` | Harness self-test: sandbox cleanup, scoring determinism, monotonic timers, fixture/trace integrity |
| `snapshot --source DIR --output F [--changelog S] [--verify]` | Generate/verify hashed dataset snapshots |
| `validate --path PACK` · `task validate/test/scaffold` | Schema validation, pack tests, scaffolding |

## Ingestion (external traces)

| Command | Purpose |
|---|---|
| `ingest --format otel-spans\\|--format openai-steps --in FILE [--out JSONL] [--task-id] [--agent]` | Convert external traces into ToolTrace trace events; prints event counts and the classified failure reason. OTel GenAI spans come from any OpenTelemetry-instrumented agent framework; OpenAI steps are plain assistant-message/tool-call logs |

Ingested traces flow through `tooltrace trace`, replay and scoring unchanged — see
[`tooltrace.ingest`](../tooltrace/ingest/__init__.py). The pytest plugin (`pytest11`
entry point) exposes `run_tooltrace` / `assert_tooltrace_pass` fixtures so tasks run
as native pytest tests; see [Plugins](plugins.md).

## Server mode

| Command | Purpose |
|---|---|
| `server [--host] [--port]` | Self-hosted API: REST + SSE + `/metrics` + `/healthz` + `/readyz` + `/openapi.json` (RBAC, quotas, audit) |

See [Self-hosting](self-hosting.md) for tokens, roles and policies.