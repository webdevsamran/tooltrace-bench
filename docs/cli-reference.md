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

## Server mode

| Command | Purpose |
|---|---|
| `server [--host] [--port]` | Self-hosted API: REST + SSE + `/metrics` + `/healthz` + `/readyz` + `/openapi.json` (RBAC, quotas, audit) |

See [Self-hosting](self-hosting.md) for tokens, roles and policies.