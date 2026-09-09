# Scoring production traces

GitHub Copilot, Codex and Claude Code emit OpenTelemetry GenAI spans directly,
and `tooltrace ingest` has always been able to read them. What it could not do
was *score* them, so a real agent run could be converted and classified but
never graded.

```bash
tooltrace ingest --format otel-spans --in prod-trace.json \
  --score-against tool-call-structure/read-before-write --json
```

## Why this works at all

A production trace has no workspace. By the time anyone looks at it, the
filesystem the agent operated on is gone, so every `(params, workspace)`
assertion is unanswerable — which is why this was not possible before the
trace-aware scorers existed (see [tool-call-structure.md](tool-call-structure.md)).

Trace assertions ask about the trajectory: which tools were called, with what
arguments, in what order, and whether any failed. A trace carries all of that,
so those assertions can be evaluated against a real production run.

## Partial scores are labelled partial

`--score-against` reports three things a caller needs together:

| Field | Meaning |
|---|---|
| `score` | The weighted score over the assertions that *could* be evaluated |
| `skipped_assertions` | The assertions that need a workspace, by name |
| `is_partial_score` | True whenever anything was skipped |

A partial score presented as a complete one would be the worst possible output
here: it understates an agent by exactly the assertions nobody could evaluate.
So the omission is returned explicitly and echoed on stderr, and a task with no
trace assertions at all says so rather than reporting a score of zero.

## Exporting the other way

`tooltrace/exporters/otel.py` turns a result into GenAI spans, so results flow
into Langfuse, Phoenix, Datadog or any OTel backend. Being the harness that
*feeds* those platforms is a better position than competing with them.

Spans are plain dicts in the OTLP JSON shape rather than SDK objects: adding an
OpenTelemetry SDK dependency to an offline-first, supply-chain-audited project —
for what is a documented attribute vocabulary — is a poor trade. **Nothing is
transmitted.** The exporter produces spans; sending them is the caller's
decision, with the caller's collector and network policy. A test asserts the
module imports no HTTP client at all.

Every span records `gen_ai.conventions.version`, because the GenAI semantic
conventions are still experimental upstream and undated telemetry is unreadable
a year later.

## What this does not measure

- **Not the workspace.** Anything about files, diffs or produced artifacts is
  unanswerable from a trace and is reported as skipped, never as failed.
- **Not cost, unless the trace carries it.** Token attributes are emitted only
  when the run reported them; absent is absent, never zero.
- **Round-trip fidelity is structural, not total.** A failed tool call is
  exported without a result attribute, because `from_otel_spans` derives status
  from that attribute's presence — but a trace is a summary, and re-importing
  one does not reconstruct the run.
