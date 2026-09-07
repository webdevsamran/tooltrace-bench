# ToolTrace Bench

**Vendor-neutral, reproducible benchmarking of AI agents** across coding, tool use, file operations, multi-step workflows, failure recovery, latency, cost and reliability.

- **Creator / Founder / Lead Maintainer:** [@webdevsamran](https://github.com/webdevsamran)
- **License:** Apache-2.0
- **Status:** Beta (v0.3.0)

---

## The problem

Most agent benchmarks optimize for headline scores. They rarely answer the questions that matter when you actually deploy an agent:

- Can the agent **finish** the task — and can you prove it deterministically?
- Does it **use tools correctly**, or does it hallucinate tools and arguments?
- Can it **recover** when a tool or command fails?
- How many **steps and tool calls** does it need?
- Does it make **unnecessary or destructive changes**?
- Is it **consistent** across repeated runs?
- How much **wall / model / tool time**, and what **token/cost** data is available?
- Does reliability **degrade as context grows**?

ToolTrace Bench is a **reliability laboratory**, not a leaderboard hype machine. It emphasizes repeatability, tool behavior, failure recovery, complete traces, and CI regression gates — locally and offline by default.

## 60-second quickstart

```bash
# 1. Install (Python 3.11+)
pip install -e ".[dev]"

# 2. Check your environment
tooltrace doctor

# 3. List the bundled deterministic tasks
tooltrace tasks

# 4. Run a single task with the deterministic scripted agent
tooltrace run --task file-editing/fix-config-typo --agent scripted

# 5. Inject safe faults and measure recovery
tooltrace perturb --task failure-recovery/retry-after-tool-failure --agent scripted --runs 3

# 6. Write a bundle, then inspect exactly why the run passed or failed
tooltrace run --task file-editing/fix-config-typo --agent scripted --out runs/
tooltrace trace runs/<bundle>.tooltrace --assertions

# 7. Repeat a benchmark across tasks (reliability across N runs)
tooltrace benchmark --task file-editing/fix-config-typo,bug-fixing/fix-off-by-one \
    --agent scripted --runs 3 --summary

# 8. Compare two runs (only identical task/protocol versions compare)
tooltrace compare runs/run-A.tooltrace runs/run-B.tooltrace
```

`--out` takes a *directory*; the bundle inside it is named from the task, agent
and run id, and `tooltrace run` prints that name.

Every run produces a **`.tooltrace` bundle**: `result.json`, `trace.jsonl`, `task.yaml`, `environment.json`, `workspace.diff`, `scoring.json`, and SHA-256 checksums — reproducible with `tooltrace reproduce <bundle>`.

## A sample run

Captured from an actual `tooltrace run` on 2026-09-07, not hand-written. The
`scripted` agent replays a fixed tool-call script, so the pass/fail outcome,
step counts and score components below are deterministic and you should
reproduce them exactly; only the timings will differ.

```console
$ tooltrace run --task file-editing/fix-config-typo --agent scripted --json
{
  "result": {
    "schema_version": 1,
    "framework_version": "0.3.0",
    "run_id": "8e788323a488",
    "task_id": "file-editing/fix-config-typo",
    "task_version": "1.0.0",
    "task_protocol_version": 1,
    "agent": "scripted",
    "success": true,
    "partial_success": false,
    "score": {
      "total": 1.0,
      "components": {"typo removed": 1.0, "correct key present": 1.0},
      "weights": {"typo removed": 1.0, "correct key present": 1.0}
    },
    "failure_reason": "none",
    "failure_detail": "no_failure",
    "steps": 3,
    "tool_calls": 2,
    "failed_tool_calls": 0,
    "invalid_tool_calls": 0,
    "repeated_calls": 0,
    "unnecessary_changes": 0,
    "workspace_violations": 0,
    "test_pass_ratio": null,
    "wall_ms": 12.717,
    "model_ms": null,
    "tool_ms": 12.412,
    "usage": {"tokens": null, "model_time_ms": null, "provider_cost_reported": null, "currency": null},
    "trust_state": "LOCAL",
    "started_at": "2026-09-07T06:39:00.913248+00:00",
    "finished_at": "2026-09-07T06:39:00.947706+00:00"
  },
  "diff": "--- config.ini\n+++ config.ini\n@@ -1,4 +1,4 @@\n [server]\n host = localhost\n port = 8080\n-timout = 30\n+timeout = 30"
}```

Two things worth noticing, because they are the point of the tool. Score
`components` are the task's own human-readable assertion labels, not scorer
function names — you can read *why* it passed. And `model_ms`, `usage.tokens`
and `test_pass_ratio` are `null` rather than zero: the scripted agent involves
no model, and an unmeasured quantity is never reported as a number.

`trust_state` is `LOCAL` because this ran on an unattested machine. That is
the honest default; it is not a verified published result.

## Architecture (1-minute tour)

```
task pack (YAML) ──► TaskDefinition (schema-validated)
                          │
                          ▼
                   Sandbox (temp workspace, network off by default)
                          │
   AgentAdapter ──actions──► Tool registry (typed tools, sanitized events)
   (subprocess /            │
    OpenAI-compatible /     ▼
    scripted)          Trace (versioned JSONL: every request/result/diff)
                          │
                          ▼
              Deterministic scorers ──► Score + FailureReason
                          │
                          ▼
        EvalResult ──► .tooltrace bundle ──► reports / compare / regression
```

Details in [ARCHITECTURE.md](ARCHITECTURE.md). The sandbox threat model is in [docs/threat-model.md](docs/threat-model.md).

## Task types shipped

Thirteen packs, nineteen tasks. `tooltrace tasks` prints the authoritative list
with difficulty; the pack directory names below are the ones you pass to
`--task`.

| Pack | Focus |
|---|---|
| `file-editing` | targeted edits to config and source files |
| `bug-fixing` | bug fixing against a failing test |
| `test-repair` | repairing broken test expectations |
| `refactoring` | behaviour-preserving renames |
| `docs-correction` | documentation correction |
| `json-csv-transform` | JSON/CSV transformation |
| `git-workflow` | git workflows (staging, commits) |
| `shell-workflow` | shell workflows and directory structure |
| `mock-api` | local mock-API state tasks |
| `data-analysis` | data analysis over fixtures |
| `multi-step-planning` | multi-step planning |
| `failure-recovery` | recovery under injected perturbations, including a compositional task where three faults compound |
| `long-context` | context-scaling family (1k / 4k / 16k) |

Two tasks in `shell-workflow` exercise **compiled-language** workflows, where
the failure is a compiler diagnostic before anything runs rather than a runtime
traceback. They declare `requires_tools` (`go`, `cargo`) and are **skipped, not
failed**, on machines without those toolchains -- scoring a missing compiler as
an agent failure would make results depend on the runner rather than the agent.
`tooltrace tasks` reports `runnable_here` for each.

## Adapter model

Agents implement a small, stable interface: `initialize`, `run`, an **event stream**, **usage metadata**, and **artifacts/final output**. Discovery is plugin-based via the `tooltrace.agents` entry-point group.

- `subprocess` — run any agent CLI inside the sandbox (opaque, one step).
- `openai_compat` — an agentic loop against any OpenAI-compatible HTTP endpoint (e.g. a local server). Provider SDKs are **not** required; provider-specific integrations stay optional extras.
- `streaming` — drive a local agent process that emits **one event per step** over NDJSON on stdin/stdout. The per-step counterpart to `subprocess`: instead of one opaque blocking call, the trace records the actual sequence of decisions. Fully offline (a child process, not a network call) and framework-agnostic — anything that can print a line of JSON can be driven by it. See [`examples/streaming_agent.py`](examples/streaming_agent.py) for a runnable reference.
- `scripted` — deterministic tool-call scripts for CI, tests and reproducible examples.

## pytest integration & trace ingestion

Install once and ToolTrace tasks run as ordinary pytest tests:

```python
def test_agent_edits_file(run_tooltrace, assert_tooltrace_pass):
    result, events, diff = run_tooltrace(task, "scripted", {"script": [...]})
    assert_tooltrace_pass(result)   # failure taxonomy reason + score in the message
```

Traces produced *outside* the harness can be scored too: `tooltrace ingest`
converts OpenTelemetry GenAI spans or plain OpenAI assistant-step logs into
ToolTrace trace events, which then flow through classification, replay and
scoring unchanged. See [docs/cli-reference.md](docs/cli-reference.md).

## Frontend

A production-quality React + TypeScript + Vite app lives in [`web/`](web/): leaderboard with domain heatmaps, agents, models, task packs, result detail with trace timeline / tool-call viewer / workspace diff viewer, compare, reliability trends with running pass-rate curves, failure analysis, cost·latency·efficiency charts, virtualized Trace Explorer with raw JSONL download, recovery analysis, dataset browser, plugin catalog, methodology, docs, contributors and about. It renders **only validated repository data** — static JSON indexes are generated from real result bundles and deployed via GitHub Pages.

The same component model also powers the **self-hosted team console** (`/workspace`): experiments + builder with live SSE progress, workers/capacity, baselines & regressions, Task Authoring Studio, publication review queue, users & service accounts, policies & budgets, audit log, webhooks, retention/settings and system health. Point it at your own `tooltrace server` for live REST/SSE data; without a server it offers an explicitly labeled DEMO preview and never mixes demo rows into public pages. Dark/light mode, accessibility (axe-gated), global search, shareable filters, sortable/paginated tables, route-level code splitting, error boundaries and raw-data downloads are built in.

## Supported platforms

Every row below is what CI actually runs on each push, not an aspiration.

| Platform | Coverage |
|---|---|
| Linux (`ubuntu-latest`) | Full suite, coverage gate, lint, types, dependency audit, frontend build, Playwright e2e and accessibility checks |
| Windows (`windows-latest`) | Full Python suite |
| macOS (`macos-latest`) | Full Python suite |

| Python | Coverage |
|---|---|
| 3.11, 3.13, 3.14 | Full Python suite on Linux |
| 3.12 | Full suite plus coverage gate, lint, types and schema validation |

Node 22 is required for the frontend: `jsdom` pulls `undici@8`, which declares
`engines.node: ">=22.19.0"`.

Two caveats worth stating rather than leaving implied:

- **The sandbox's container provider is not exercised on Windows or macOS.**
  Conformance checks for it run on Linux only, so isolation guarantees are
  verified there and inferred elsewhere. Hardening this across providers is
  tracked in [#12](https://github.com/webdevsamran/tooltrace-bench/issues/12).
- **The frontend is built and tested on Linux only.** It is a static site, so
  the build output is platform-independent, but no browser test runs on
  Windows or macOS.

## Documentation

Full docs hierarchy in [`docs/`](docs/index.md): [getting started](docs/getting-started.md),
[CLI reference](docs/cli-reference.md) (incl. `lint`, `dry-run`, `self-test`, `snapshot`,
`server`), [architecture pipeline](docs/architecture-pipeline.md),
[self-hosting & teams](docs/self-hosting.md) (RBAC, policy-as-code, audit, quotas,
signed webhooks), [security threat model](docs/threat-model.md),
[competitive analysis](docs/competitive-analysis.md), [troubleshooting/FAQ](docs/troubleshooting-faq.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are labeled `good first issue` in the tracker; meaningful contribution areas include task packs, adapters, deterministic scorers, sandbox providers, frontend and analysis algorithms.

## Citation

See [CITATION.cff](CITATION.cff), or:

```bibtex
@software{tooltrace_bench,
  author  = {Samran (webdevsamran)},
  title   = {ToolTrace Bench: vendor-neutral, reproducible benchmarking of AI agents},
  year    = {2026},
  url     = {https://github.com/webdevsamran/tooltrace-bench},
  license = {Apache-2.0}
}
```

## Attribution

ToolTrace Bench was created and is led by **@webdevsamran**. See [AUTHORS](AUTHORS) and [MAINTAINERS](MAINTAINERS).