# ToolTrace Bench

**Vendor-neutral, reproducible benchmarking of AI agents** across coding, tool use, file operations, multi-step workflows, failure recovery, latency, cost and reliability.

- **Creator / Founder / Lead Maintainer:** [@webdevsamran](https://github.com/webdevsamran)
- **License:** Apache-2.0
- **Status:** Beta (v0.1.0)

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

# 3. List bundled deterministic task packs
tooltrace tasks

# 4. Run a single task with the deterministic scripted agent
tooltrace run --task fileops/copy-and-rename --agent scripted

# 5. Run a repeated benchmark (reliability across N runs)
tooltrace benchmark --pack fileops --agent scripted --runs 3

# 6. Compare two runs (only identical task/protocol versions compare)
tooltrace compare runs/run-A.tooltrace runs/run-B.tooltrace
```

Every run produces a **`.tooltrace` bundle**: `result.json`, `trace.jsonl`, `task.yaml`, `environment.json`, `workspace.diff`, `scoring.json`, and SHA-256 checksums — reproducible with `tooltrace reproduce <bundle>`.

## A real sample run

The bundled `scripted` agent replays a deterministic tool-call script, so the sample below is a genuine, reproducible evaluation (no model required, no fabricated numbers):

```console
$ tooltrace run --task fileops/copy-and-rename --agent scripted --json
{
  "task_id": "fileops/copy-and-rename",
  "task_version": "1.0.0",
  "agent": "scripted",
  "success": true,
  "score": {"total": 1.0, "components": {"file_exists": 1.0, "file_contains": 1.0}},
  "steps": 3,
  "tool_calls": 3,
  "failed_tool_calls": 0,
  "recovery_rate": null,
  "wall_ms": 41,
  "bundle": "runs/fileops-copy-and-rename-scripted.tooltrace"
}
```

Your exact timings will differ; the pass/fail outcome, step counts and trace are deterministic.

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

Details in [ARCHITECTURE.md](ARCHITECTURE.md). The sandbox threat model is in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Task types shipped

| Pack | Focus |
|---|---|
| `fileops` | file editing, copy/rename, patching |
| `bugfix` | bug fixing with failing tests |
| `testrepair` | repairing broken tests |
| `refactor` | behavior-preserving refactoring |
| `docsfix` | documentation correction |
| `datatransform` | JSON/CSV transformation |
| `gitwork` | git workflows (staging, commits, branches) |
| `shellwork` | shell workflows |
| `mockapi` | local mock-API state tasks |
| `dataanalysis` | data analysis over fixtures |
| `planning` | multi-step planning |
| `recovery` | failure recovery under injected perturbations |

## Adapter model

Agents implement a small, stable interface: `initialize`, `run`, an **event stream**, **usage metadata**, and **artifacts/final output**. Discovery is plugin-based via the `tooltrace.agents` entry-point group.

- `subprocess` — run any agent CLI inside the sandbox (opaque, one step).
- `openai_compat` — an agentic loop against any OpenAI-compatible HTTP endpoint (e.g. a local server). Provider SDKs are **not** required; provider-specific integrations stay optional extras.
- `scripted` — deterministic tool-call scripts for CI, tests and reproducible examples.

## Frontend

A production-quality React + TypeScript + Vite app lives in [`web/`](web/): leaderboard, agents, models, task packs, result detail with trace timeline / tool-call viewer / workspace diff viewer, compare, reliability trends, failure analysis, methodology, docs, contributors and about. It renders **only validated repository data** — static JSON indexes are generated from real result bundles and deployed via GitHub Pages, so no backend is required. Dark/light mode, accessibility, global search, shareable filters, sortable/paginated tables, and raw-data downloads are built in.

## Documentation

Full docs hierarchy in [`docs/`](docs/index.md): [getting started](docs/getting-started.md),
[CLI reference](docs/cli-reference.md) (incl. `lint`, `dry-run`, `self-test`, `snapshot`,
`server`), [architecture pipeline](docs/architecture-pipeline.md),
[self-hosting & teams](docs/self-hosting.md) (RBAC, policy-as-code, audit, quotas,
signed webhooks), [security threat model](docs/THREAT_MODEL.md),
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