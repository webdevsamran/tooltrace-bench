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

## After the incident: turn it into a task

`ingest` converts a production trace into this project's event format and
`score_trace_only` scores what a trajectory alone can answer. Both stop one step
short of what anyone wants after an incident, which is to make sure it does not
happen again.

`tooltrace promote-trace` takes that step, and is careful about which half of the
job is mechanical.

**What it generates.** The tools called, in order, with their argument *shapes* --
not their values. Pinning the exact paths from one incident would produce an
assertion that only ever matches that incident. Plus a "no failed calls"
assertion, but only when the incident actually had failures: generating it for a
clean trace would assert something the incident never demonstrated.

**What it refuses to generate.** A workspace, an expected output, or any
correctness assertion. A production trace does not contain the filesystem it ran
against, and a task with an invented workspace tests the invention. Those
sections ship empty with a `TODO` naming each, and `readiness()` reports the
draft as unfinished until a human fills them in -- including the specific warning
that a trajectory-only task passes for an agent that made all the right calls and
produced the wrong result.

**And it never claims to reproduce the incident.** It encodes the trajectory the
incident had. Whether that trajectory is *why* it failed is a judgement for
whoever saw it.

## Drift, and the failure a success-rate monitor cannot see

Half of enterprises have shipped an agent that passed internal evaluation and
still caused a customer-facing failure. That gap is usually not a break; it is a
slide -- a model updated behind an API, a prompt edited, a tool's output format
changed.

`tooltrace drift` compares two windows across five metrics rather than one, and
the reason is a specific case: **an agent whose success rate is unchanged while
its step count doubled has changed.** A rate-only monitor is structurally unable
to report it. When that happens the output sets `silent_decay` and says outright
that an accuracy-only monitor would have reported nothing.

Two things have to hold before drift is claimed, the same discipline
`pr-report` uses: the intervals must not overlap, *and* the move must exceed a
stated threshold. A monitor that fires on noise gets muted, and a muted monitor
is worse than none because it is believed to be watching.

Windows below ten runs report `measurable: false` rather than a verdict.

## Error budgets

"99% reliability" is unactionable. "Four failures of budget left this window" is a
decision, and it is the same number expressed usefully. `--objective` reports it.

Two deliberate choices:

- **The remaining budget goes negative** rather than clamping at zero. "At the
  limit" and "eleven over" call for different responses, and clamping erases the
  difference.
- **`objective_is_within_interval`** says when the window cannot settle the
  question at all. Ten runs with no failures do not establish a 99% objective;
  the interval contains it, and the statement says so.

## Sampling: which traces to score when you cannot score them all

At a few thousand traces a day, scoring everything is a bill that arrives every
day. Something has to choose, and the choice is where most of the damage in a
production evaluation pipeline gets done.

**Uniform random sampling is the usual default and the wrong one.** The thing
worth finding is failure, and failure is rare. Sample 1% of traffic uniformly
and you see 1% of the failures: a class that happens twice a week becomes a
class you see roughly once a year, and every review meeting looks at a sample in
which everything worked.

The default here is stratified:

| Stratum | Kept | Why |
|---|---|---|
| `errored` | 100% | What the pipeline exists to find, and rare enough that sampling it at all loses most of it |
| `long` | 25% | More than 25 steps. An agent that took forty steps to *succeed* has a problem the success rate cannot see |
| `clean` | 1% | For a baseline, not for discovery |

### The correction is the feature

A stratified sample is **biased on purpose**, and any rate computed directly
from it is a statement about the sampling policy rather than about the agent. On
a population with a 2% failure rate, a sample that keeps every error reads at
around 70%.

`estimate_rate` inverts the sampling weights and recovers the population figure.
It uses the **realised** rate per stratum rather than the requested one -- with a
small population they differ, and projecting from a rate that was never taken
would be arithmetic about an intention. It also reports how many scored traces
each stratum's contribution rests on: a stratum sampled down to three traces
contributes an estimate wide enough to swallow the answer, and that is said
rather than averaged in silently.

### Determinism

Selection is a hash of the trace id and the seed, not a draw from a random
number generator. A sequence-dependent draw would make the sample depend on the
order traces arrived in, so a re-run that processed them differently would keep
a different set -- which would quietly make a sampled evaluation unreproducible.

A trace with no id is kept rather than dropped: losing one because it was
missing a field would bias the sample in a direction nobody chose.

When `--out` is given, the policy is written beside the sample. A kept subset on
its own is a file nobody can correct for later.
