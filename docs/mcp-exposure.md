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

## Fuzzing a server, and what it found here

`mcp-conformance` asks a server to do things correctly and checks that it does.
`mcp-fuzz` asks it to do things incorrectly and checks that it refuses, which is
the half that finds real defects -- a server is written against the happy path and
tested against the happy path.

The cases are specific rather than random. Random bytes at a JSON-RPC server
mostly produce parse errors, which every implementation handles identically and
which tell you nothing. These are the shapes implementations actually get wrong:
a missing `jsonrpc` version, a method that is not a string, `params` that is a
string, a `tools/call` with no name, a truncated line, an empty object.

Three severities, and the middle one is why this is a measurement rather than an
opinion:

| Severity | Meaning | Fails |
|---|---|---|
| `must_reject` | Accepting it is a protocol violation with security consequences | yes |
| `should_reject` | The spec says no; a tolerant server is sloppy, not broken | no |
| `may_reject` | Either behaviour conforms | no |

**A crash is always a problem**, whatever the severity class says. A server that
dies on optional input is a denial-of-service surface, and so is one that hangs.

### It found three crashes in this project's own fixture

The first run against `FAKE_SERVER_SCRIPT` -- the server `mcp-conformance` checks
when nobody names one, and therefore the example this project holds up as
*conforming* -- crashed it three times:

- `json.loads` was unguarded, so a truncated line raised.
- `tools/call` reached into `msg["params"]["name"]` without checking that
  `params` was a mapping.
- ...or that `name` was present at all.

All three are now guarded, and every guard answers with a JSON-RPC error rather
than staying silent, because a client cannot tell silence from a hang. The
fragile version is kept verbatim in `tests/test_mcp_fuzz.py` as the thing the
fuzzer has to catch: a fuzzer that finds nothing is indistinguishable from a
working system.

The fixture still *accepts* three `should_reject` cases -- a missing version
field, a `1.0` version, an object id. That is tolerance rather than breakage, it
is reported, and it does not fail.
