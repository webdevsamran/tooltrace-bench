# CLI Reference

All commands accept `--json` for structured output.

Exit codes: `0` ok · `2` usage · `3` task/validation · `4` agent · `5` run failure · `8` regression threshold · `9` secrets detected · `130` interrupted.

## Core workflow commands

| Command | Purpose |
|---|---|
| `doctor` | Environment, all four registries (tools, agents, scorers, sandboxes) and plugin discovery |
| `init [--agent A\|ollama\|llama_cpp\|lm_studio\|vllm\|sglang] [--command CMD] [--dir D] [--task ID] [--no-ci] [--no-run] [--force]` | Set up this project against **your** agent: writes `tooltrace.config.json` and a CI workflow, then runs one real task and reports the outcome. Overwrites nothing without `--force`, and never writes a credential — `openai_compat` gets the *name* of an env var. A failing first run is still a successful init: that is a measurement, not a setup problem |
| `tasks [--category]` | List bundled tasks |
| `agents` | List registered agent adapters, including any a plugin contributed |
| `tools [--dialect openai\|anthropic\|mcp\|gemini\|prompt] [--equivalence]` | What a model is actually told about the tools it may call: name, description and the declared argument schema. `--dialect` renders the catalogue as one provider receives it, which is the only way to see that a schema survives the translation -- Gemini rejects `oneOf` and half the other JSON Schema keywords, and narrowing a union there is reported in the description rather than done silently. The plain output ends with how many registered tools declare a schema at all, because "nothing is validated" and "everything passed validation" look identical from outside. `--equivalence` asks the other question: does declaring a tool *once* mean the same thing to all four? The comparison is on meaning rather than bytes -- a dialect that renames a key is equivalent, one that drops a constraint is not |
| `backends [--json]` | Local model servers this project knows -- Ollama, llama.cpp, LM Studio, vLLM, SGLang -- with their ports, model-name conventions and which is listening. All five speak the OpenAI chat API and run through the one `openai_compat` adapter; detection probes **localhost only**, and an open port is evidence something is listening rather than a positive identification of the server |
| `run --task ID --agent A [--agent-config JSON] [--out DIR]` | One deterministic task against one agent; writes a bundle |
| `benchmark --agent A [--runs N] [--task ids] [--limit N] [--shuffle] [--seed S] [--context-sweep] [--min-success-rate] [--budget X]` | Repeated reliability runs with pass@k/pass^k-aware summaries and trajectory metrics. `--limit` runs a recorded subset for CI; the policy, seed and selected ids are reported and a subset announces itself on stderr. `--budget` is a **hard** ceiling: the sweep stops rather than continuing, warns at 80%, and the summary reports what did not run. An unpriced run is not counted against it, and the budget says so |
| `power [--runs N \| --detect D] [--baseline-rate R]` | What a planned sweep can detect, before you spend anything on it. Detecting a 10-point difference at a 50% baseline needs ~393 runs per arm; a 5-point difference ~1570 |
| `showdown --agents a,b [--runs N] [--limit N] [--shuffle] [--seed S]` | Fair multi-agent ranking on identical cohorts. Emits `{standings, verdict, note, ranking_is_provisional}`; the verdict is `ranked` only when the sample is large enough *and* the leader's confidence interval clears the runner-up's, otherwise `not distinguishable at this sample size`. Also carries a `power` block (what this sample could have detected, which is what makes that verdict readable), a Beta-Binomial `bayesian` posterior, and a `variance` split separating nondeterminism from task diversity |
| `compare --baseline B --current C [--metrics m1,m2]` | Metric-by-metric comparison of two **single-run** bundles |
| `pr-report --baseline DIR --current DIR [--out F] [--metrics m1,m2]` | Compare two *sets* of runs and render a pull-request comment. Four verdicts per metric: `regressed`, `improved`, `no_change_detected`, `inconclusive`. Only an established regression exits non-zero (8) — a change has to be both real (its interval excludes zero) and large enough to matter. Refuses to compare different task sets or artifact versions. `--metrics` narrows the gate: on a shared CI runner `wall_ms` is wall-clock rather than a property of the agent, and a gate that fails because of a noisy neighbour gets switched off -- which costs the four metrics that were worth gating on |
| `baseline --name N --bundle PATH` | Record a named baseline |
| `regression --baseline B --current C --thresholds JSON` | CI gate for score/tool/latency regressions |
| `a2a-card CARD [--key KID=SECRET]` | Check an A2A Agent Card, and say what its signature does and does not prove. Conformance and provenance are separate: a card can be perfectly formed and unsigned, and most in the wild are. **The verification key comes from you, never from the card** -- a signature checked against a key the document itself names proves only that the document agrees with itself. An algorithm this package cannot verify is reported `no_verifier` rather than assumed valid |
| `mcp-conformance [--url URL] [-- COMMAND...]` | Check an MCP server against the protocol, over stdio or HTTP. `--url` reaches a hosted server; the checks do not change with the transport, which is the point of running them over each. Exits non-zero only on a *required* failure; a missing tool description is reported as recommended, not a violation. Defaults to the bundled fixture |
| `mcp-scan (--from FILE \| --registry URL) [--markdown]` | Score many MCP servers at once: conformance, protocol versions and malformed input per server, worst first. **A `command` may only come from a file on this machine.** A registry fetched over the network contributes URL targets and nothing else -- executing a command string that arrived from a server on the internet is remote code execution, and a reputable registry changes how likely that is to be abused, not what the code does. A fetched entry naming a command is reported as skipped with the reason, because a silent drop reads as a pass |
| `mcp-versions [--markdown] [--url URL] [-- COMMAND...]` | Handshake once per published MCP revision and report what came back. Neither `supported` nor `unsupported` is the finding: answering a revision you do not implement with one you do is correct negotiation. The finding is a server that **echoes back whatever it was sent**, which is why a version that cannot exist is in the list -- such a server is agreeing rather than negotiating, and the mismatch surfaces later as a field missing for no visible reason |
| `mcp-fuzz [--markdown] [-- COMMAND...]` | Send malformed JSON-RPC at an MCP server and report what it did. Three severities: accepting a `must_reject` case is a violation, tolerating a `should_reject` one is sloppy and does not fail, and a `may_reject` case conforms either way. **A crash is always a problem** -- a server that dies on malformed input is a denial-of-service surface whatever the spec says about the input |
| `evidence --bundles DIRS [--out DIR]` | Assemble an evidence dossier for a regulated review: runs, verification status, and what each obligation is and is not evidenced by. Never a compliance determination |
| `verify BUNDLE [--no-schema] [--no-integrity] [--signature F]` | Check a bundle's checksums, schema conformance and anti-gaming integrity (dropped assertions, a task modified after publication, an expected answer visible in the prompt); read-only, exits 5 on any problem. `--signature` additionally verifies a cosign signature: checksums are tamper-*evident* (they detect a change), a signature establishes *who* produced the bundle |
| `reproduce BUNDLE [--out DIR] [--no-rerun]` | Verify hashes and optionally re-run |
| `attest BUNDLE [--attester WHO] [--signature S] [--promote]` | Reproduce a bundle and record who did it. **A re-run on the machine that produced the bundle stays `LOCAL`** -- it demonstrates determinism, not independent reproduction. An unsigned attestation from another machine reaches `COMMUNITY_VALIDATED`; a signed one reaches `REPRODUCED`. `MAINTAINER_VERIFIED` is never awarded by a machine |
| `card [--bundles DIR] [--agent A] [--out F]` | A system card generated from recorded runs. A task with fewer than 10 runs is reported as insufficiently measured rather than as a capability or a limitation, and the *not measured* section is generated too |
| `self-audit [--bundles DIR]` | Would the evidence you hold demonstrate anything? A checklist with named gaps, deliberately not a percentage. Exits 0 even with gaps: a gap is a finding, not a build failure |
| `perturb --task ID [--perturbation kind:tool] [--runs N] [--min-recovery-rate R]` | Inject safe faults and measure recovery rate; `--out` writes bundles |
| `drift --current DIR [--baseline DIR] [--objective R]` | Has behaviour moved between two windows of runs? Watches five metrics, not just accuracy -- an agent whose success rate held while its step count doubled has changed, and `silent_decay` names that case. `--objective` turns an SLO into an error budget: how many failures are left |
| `promote-trace TRACE --task-id ID [--out F]` | Turn a production trace into a **draft** regression task. Generates the trajectory assertions and refuses to invent a workspace or a correctness assertion, leaving a `TODO` for each -- a generated task that looked finished would run, pass, and test nothing |
| `trace BUNDLE [--filter SUBSTR] [--assertions] [--limit N]` | Inspect a bundle trace in the terminal (checksum-verified) |

## Reporting / export

| Command | Purpose |
|---|---|
| `report --bundles DIR... [--format json\|csv\|md\|junit\|html] [--output F]` | Aggregate bundles into a report |
| `badge (--summary F \| --bundles DIR) [--out F] [--svg-url U] [--link U]` | Render an embeddable reliability badge. The sample size is always in the message, and the colour comes from the confidence interval's **lower bound** rather than the rate — 10 of 10 runs is 100% with a lower bound near 72%, so it renders amber, not green. Writes a shields.io `endpoint` JSON beside the SVG |
| `cost --bundles DIR [--forecast-tasks N --forecast-runs N] [--human-baseline X]` | Where the money went (by task, and by how the run ended), what a planned sweep would cost, and whether it beats a human baseline. `--human-baseline` has no default: a viability verdict against an invented baseline is an opinion, not a measurement |
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
| `owasp [--markdown]` | OWASP Agentic Top 10 coverage, computed from the installed packs. A category counts as covered only when a task declares it *and* that task runs here; `declared, not runnable` is a third state because nothing has been measured |
| `lint [--path PACK]` | Task-lint: ambiguous scoring, unreachable assertions, undeclared side effects, missing cleanup, unsafe network, and `allowed_tools` naming a tool that is not registered (every call to which fails as "unknown tool", so every agent appears to satisfy any assertion depending on it) |
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