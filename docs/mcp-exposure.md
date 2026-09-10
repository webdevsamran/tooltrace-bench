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

## Which revision does it actually implement?

`mcp-conformance` checks one revision -- whichever the client happened to ask
for. That is the wrong question for a server that has to interoperate with
clients released over two years. `mcp-versions` runs the handshake once per
published revision, on a fresh process each time, and records what came back.

Neither answer you would expect is the finding:

| Outcome | Meaning | Problem |
|---|---|---|
| `agreed` | The server implements the revision it was asked for | no |
| `downgraded` | It answered with a different published revision -- correct negotiation | no |
| `rejected` | It refused, which is a legitimate answer | no |
| `echoed_unknown` | It answered with the revision it was *sent*, including one that never existed | **yes** |
| `no_version` | The handshake completed without saying which protocol it settled on | **yes** |
| `crashed` | The process died or never started | **yes** |

The finding is `echoed_unknown`. A server that repeats the client's field is
agreeing rather than negotiating: the client proceeds believing it settled on a
protocol, and the mismatch surfaces later as a field that is missing for no
visible reason.

Catching it requires sending a revision that **cannot** exist -- `9999-01-01`.
Test only against published revisions and an echoing server passes every single
one, which is what the test named
`test_an_echoing_server_still_looks_fine_on_real_versions` pins.

## Does one tool declaration mean the same thing to four providers?

`tooltrace tools --equivalence` reads each dialect's rendering back and compares
it to the declaration it came from. Three of the four are lossless, which is
worth stating rather than assuming. Gemini is not: it cannot express `oneOf`, so
`git`'s honest union -- a list of arguments, or one string -- is narrowed to the
first branch.

That is a fact about Gemini rather than a defect in the tool, so it is reported
and does not fail. It matters because the narrowed declaration is what the model
reads: it will not send what the declaration no longer permits, whatever the
tool would have accepted.

The comparison is on *meaning*, not bytes. Anthropic moves the schema to
`input_schema` and changes nothing about it; a byte comparison would flag all
four dialects and tell nobody anything.

## Transports: stdio, HTTP, and HTTP that streams

The client here spoke stdio and only stdio, which covers a server you start
yourself as a subprocess and nothing else. Every hosted MCP server -- which is
most of the ones a team does not run itself -- is reached over HTTP, so a
conformance report that could not reach one was a report about the easy half of
the ecosystem.

The JSON-RPC is identical on all three. Only the framing differs:

| Transport | Framing | Reached with |
|---|---|---|
| stdio | one JSON object per line on the process's pipes | `-- COMMAND...` |
| HTTP | one POST per request, the reply in the body | `--url` |
| Streamable HTTP | the same POST, answered with `text/event-stream` | `--url` |

The third is why this is a transport layer rather than one `httpx.post`. A
streamed reply may carry a progress notification **before** the result, and the
content type is the server's choice made *per response* -- so a client has to
handle both on every call rather than deciding once at configuration time. A
client that reads the first `data:` frame and calls it the answer works against
every server that does not stream and breaks against every one that does.

`transport_name` reports what the server actually did rather than what was
configured: an HTTP client says `streamable-http` once a reply has arrived as an
event stream.

The bundled HTTP fixture (`tooltrace/agents/mcp_http_fixture.py`) serves the
same handshake as the stdio one, in both reply styles, and its SSE mode sends
that leading notification deliberately. A fixture that only ever sends the happy
shape proves the client handles the happy shape. It binds to `127.0.0.1` on an
ephemeral port and has no setting that would change either.
