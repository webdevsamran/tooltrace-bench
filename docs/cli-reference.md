# CLI Reference

All commands accept `--json` for structured output.

Exit codes: `0` ok · `2` usage · `3` task/validation · `4` agent · `5` run failure · `8` regression threshold · `9` secrets detected · `130` interrupted.

## Core workflow commands

| Command | Purpose |
|---|---|
| `doctor` | Environment, all four registries (tools, agents, scorers, sandboxes) and plugin discovery |
| `init [--agent A] [--command CMD] [--dir D] [--task ID] [--no-ci] [--no-run] [--force]` | Set up this project against **your** agent: writes `tooltrace.config.json` and a CI workflow, then runs one real task and reports the outcome. Overwrites nothing without `--force`, and never writes a credential — `openai_compat` gets the *name* of an env var. A failing first run is still a successful init: that is a measurement, not a setup problem |
| `tasks [--category]` | List bundled tasks |
| `run --task ID --agent A [--agent-config JSON] [--out DIR]` | One deterministic task against one agent; writes a bundle |
| `benchmark --agent A [--runs N] [--task ids] [--limit N] [--shuffle] [--seed S] [--context-sweep] [--min-success-rate]` | Repeated reliability runs with pass@k/pass^k-aware summaries and trajectory metrics. `--limit` runs a recorded subset for CI; the policy, seed and selected ids are reported and a subset announces itself on stderr |
| `showdown --agents a,b [--runs N] [--limit N] [--shuffle] [--seed S]` | Fair multi-agent ranking on identical cohorts. Emits `{standings, verdict, note, ranking_is_provisional}`; the verdict is `ranked` only when the sample is large enough *and* the leader's confidence interval clears the runner-up's, otherwise `not distinguishable at this sample size` |
| `compare --baseline B --current C [--metrics m1,m2]` | Metric-by-metric comparison of two **single-run** bundles |
| `pr-report --baseline DIR --current DIR [--out F]` | Compare two *sets* of runs and render a pull-request comment. Four verdicts per metric: `regressed`, `improved`, `no_change_detected`, `inconclusive`. Only an established regression exits non-zero (8) — a change has to be both real (its interval excludes zero) and large enough to matter. Refuses to compare different task sets or artifact versions |
| `baseline --name N --bundle PATH` | Record a named baseline |
| `regression --baseline B --current C --thresholds JSON` | CI gate for score/tool/latency regressions |
| `mcp-conformance [-- COMMAND...]` | Check an MCP server against the protocol over stdio. Exits non-zero only on a *required* failure; a missing tool description is reported as recommended, not a violation. Defaults to the bundled fixture |
| `evidence --bundles DIRS [--out DIR]` | Assemble an evidence dossier for a regulated review: runs, verification status, and what each obligation is and is not evidenced by. Never a compliance determination |
| `verify BUNDLE [--no-schema] [--no-integrity] [--signature F]` | Check a bundle's checksums, schema conformance and anti-gaming integrity (dropped assertions, a task modified after publication, an expected answer visible in the prompt); read-only, exits 5 on any problem. `--signature` additionally verifies a cosign signature: checksums are tamper-*evident* (they detect a change), a signature establishes *who* produced the bundle |
| `reproduce BUNDLE [--out DIR] [--no-rerun]` | Verify hashes and optionally re-run |
| `perturb --task ID [--perturbation kind:tool] [--runs N] [--min-recovery-rate R]` | Inject safe faults and measure recovery rate; `--out` writes bundles |
| `trace BUNDLE [--filter SUBSTR] [--assertions] [--limit N]` | Inspect a bundle trace in the terminal (checksum-verified) |

## Reporting / export

| Command | Purpose |
|---|---|
| `report --bundles DIR... [--format json\|csv\|md\|junit\|html] [--output F]` | Aggregate bundles into a report |
| `badge (--summary F \| --bundles DIR) [--out F] [--svg-url U] [--link U]` | Render an embeddable reliability badge. The sample size is always in the message, and the colour comes from the confidence interval's **lower bound** rather than the rate — 10 of 10 runs is 100% with a lower bound near 72%, so it renders amber, not green. Writes a shields.io `endpoint` JSON beside the SVG |
| `export --out DIR [--stdin]` | Run exporter plugins on a payload |
| `serve --dir web/dist [--host] [--port]` | Serve the built frontend locally |

## Agent config from a file

`--agent-config` accepts inline JSON, or `@path` to read a JSON file:

```bash
tooltrace run --task file-editing/fix-config-typo --agent subprocess --agent-config @tooltrace.config.json
```

`@path` exists so that the file `tooltrace init` writes is a file the other
commands can read. It also keeps a long config out of shell history and out of
whichever shell's quoting rules you are subject to.

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
| `ingest --format F --in FILE [--out JSONL] [--task-id ID] [--agent A] [--score-against TASK_ID]` | Convert external traces (OTel GenAI spans / OpenAI steps) into ToolTrace events, and optionally score the trajectory against a task's trace assertions; workspace assertions are reported as skipped |

Ingested traces flow through `tooltrace trace`, replay and scoring unchanged — see
[`tooltrace.ingest`](../tooltrace/ingest/__init__.py). The pytest plugin (`pytest11`
entry point) exposes `run_tooltrace` / `assert_tooltrace_pass` fixtures so tasks run
as native pytest tests; see [Plugins](plugins.md).

## Server mode

| Command | Purpose |
|---|---|
| `server [--host] [--port]` | Self-hosted API: REST + SSE + `/metrics` + `/healthz` + `/readyz` + `/openapi.json` (RBAC, quotas, audit) |

See [Self-hosting](self-hosting.md) for tokens, roles and policies.