# Should tooltrace-bench expose an MCP server?

**Verdict: mostly no — and this is the one project in the family where the
answer is not "yes".** The reading commands are fine; exposing the *running*
ones to an agent would compromise the benchmark.

This is an assessment, not a feature. Nothing here ships today.

## The direction that already exists

This project is already an MCP **client**. `tooltrace/agents/mcp.py` speaks
JSON-RPC 2.0 over stdio to any MCP server, captures a tool inventory and
records every call into the trace, with conformance fixtures exercising
`initialize` → `tools/list` → `tools/call` against a fake server.

That is the useful direction here: MCP servers are a thing this benchmark
*measures*, not a thing it needs to become.

## Why exposing the runner is a bad idea

The other three siblings answer questions. This one scores agents. Letting an
agent invoke the scorer is a different proposition, for three reasons:

1. **Contamination.** A benchmark whose tasks an agent can enumerate at will,
   through a tool the agent controls, stops measuring generalisation. The task
   corpus is deliberately fingerprinted and contamination-tracked
   (`TaskDefinitionV2.contamination`); handing out a `tools/list` of every task
   works against that on purpose.
2. **Self-evaluation.** An agent that can call `run` can run itself, retry
   until a score improves, and report the best one. Nothing in the protocol
   distinguishes that from a legitimate call, and the resulting number would be
   presented with the same provenance as an honest one.
3. **Cost and duration.** A benchmark run takes minutes and spawns sandboxes.
   Tool calls are interactive; this is not interactive work.

None of these are hypothetical failure modes of MCP — they are what happens
when the thing being measured controls the measurement.

## What would be reasonable to expose

The read side, which has none of those problems:

| Tool | Answers |
|---|---|
| `tasks` | What tasks exist, with domain and difficulty |
| `scorers` | What scorers exist and what each asserts |
| `report` | Summarise an existing result bundle |
| `compare` | Compare two committed bundles |
| `stats` | Confidence intervals and flakiness for an existing run |

Every one of these reads artifacts that already exist. None of them can be used
to obtain a score.

## What has to be true first

1. **A decision about task disclosure.** Even `tasks` hands over the corpus
   inventory. That may be fine — the tasks are public in the repository — but
   it should be a decision rather than a side effect.
2. **Bundle path confinement**, as everywhere else.
3. **Nothing that writes.** `run`, `benchmark`, `sweep` and `perturb` stay out,
   permanently, for the reasons above rather than for want of effort.

The honest summary: this project's MCP story is the client it already has. The
server would be a small convenience with a real integrity cost attached, and
the cost is larger than the convenience.
