# Why ToolTrace Bench — and when to use something else

A positioning document, written to be useful to somebody deciding rather than to
somebody already sold. It ends with the cases where a different tool is the
right answer, because a comparison that never reaches that section is marketing.

---

## The one-sentence version

> Others score the tool call, or watch production, or probe security.
> ToolTrace Bench scores the **whole run** — correctness, recovery, side
> effects, cost, latency and security resilience — and hands you a checksummed
> artifact a third party can reproduce and an auditor can accept.

## The problem this exists for

Half of enterprises surveyed in June 2026 had shipped an agent that **passed
internal evaluation and still caused a customer-facing failure**; one in four
more than once. Gartner expects 40% of enterprise AI failures by 2028 to trace
to inadequate evaluation and monitoring rather than to model capability.

The gap is not that agents are unmeasured. It is *what* gets measured. A
benchmark that reports one accuracy number cannot distinguish:

- an agent that solved the task from one that **deleted the test file**;
- an agent that recovered from a tool failure from one that **never hit one**;
- an agent that costs $0.04 a resolved task from one that costs $4.00;
- an agent that ignored a prompt injection from one that **was never shown one**;
- a real 4-point improvement from **noise on twelve runs**.

Those are different questions, and each needs a different measurement taken
during the same run. Taking them separately, later, on different samples, is how
you get a green dashboard and a customer-facing failure.

## What "scores the whole run" means concretely

Every `tooltrace` run produces a `.tooltrace` bundle: six files plus a manifest
of SHA-256 checksums, holding the task exactly as it was executed, the full
trace, the final workspace diff, the score with every assertion, and the
environment it ran in.

From that one artifact:

| Axis | What is measured | Command |
|---|---|---|
| **Correctness** | Deterministic assertions against the final workspace | `tooltrace run` |
| **Trajectory** | Tool-call AST matching, read-before-write ordering, loop detection, hallucinated resources | `tooltrace trace` |
| **Recovery** | Graded: recovered immediately, recovered slowly, or *silently wrong* | `tooltrace perturb` |
| **Side effects** | Blast radius — what the agent touched versus what it could have | `tooltrace verify` |
| **Cost** | Cost per **resolved** task, with unpriced runs excluded rather than counted as free | `tooltrace cost` |
| **Latency** | Inference time and tool time split, with hardware recorded | `tooltrace hardware` |
| **Security** | Attack success rate per class, with Wilson intervals | `tooltrace owasp` |
| **Evidence** | Dated, hash-chained dossier mapped to regulatory obligations | `tooltrace evidence` |

## Where the categories actually divide

Twenty-six projects are tracked in
[`competitive-analysis.md`](competitive-analysis.md), fetched from the GitHub API
and committed to `data/competitor-meta.json` so the table cannot drift from the
data it cites. They fall into three groups that are easy to confuse:

**Task suites** define problems. SWE-bench, tau-bench, OSWorld, WebArena, BFCL.
They are not competitors — importers ship for four of them
(`tooltrace import --format swe-bench|bfcl|tau-bench|agentbench`), because a
problem set and a harness are different things and you need both.

**Eval harnesses** run and grade. inspect_ai, promptfoo, DeepEval. This is the
category ToolTrace Bench is in, and the difference is what it grades on: the
execution trace and the final workspace, never a model's opinion of its own work.

**Tracing platforms** record production. Langfuse, Phoenix, AgentOps, Datadog.
Integration targets, explicitly — `tooltrace platforms --target …` exports to all
of them. Be the harness that feeds them, not a worse version of them.

## The four things nothing else does together

1. **Cost on the same axis as accuracy.** Researchers note costs are rarely
   reported at all. Cost per *resolved* task is a headline metric here, and an
   agent whose runs were never priced is excluded from the frontier rather than
   plotted at zero — treating unpriced as free puts it on the Pareto frontier by
   default.

2. **Security resilience as a benchmark axis.** Prompt injection is OWASP's #1
   for agentic applications and reported attack success rates reach 84%.
   Exfiltration is measured through an **offline egress sink**: the `http_post`
   tool performs zero network I/O and appends to a log inside the workspace, so
   an exfiltration attempt becomes an ordinary workspace observation that
   ordinary scorers can check.

3. **Statistics that refuse to over-claim.** `showdown` will not name a winner
   the sample cannot support. Comparisons use Newcombe difference-of-Wilson
   intervals; `power` reports the minimum detectable effect *before* you spend
   the money; variance decomposition separates the model's nondeterminism from
   the harness's.

4. **Evidence a reviewer can accept.** Checksummed, tamper-evident,
   reproducible, hash-chained. The EU AI Act's operative demand is that
   organisations **demonstrate** compliance rather than assert it, and a bundle
   somebody else can re-run is the difference.

## When to use something else

- **You need a red-teaming platform with a large prompt corpus and a UI for
  iterating on prompts.** Use **promptfoo**. This project measures whether an
  agent's *behaviour* holds up, not whether a prompt phrasing is better.

- **You need a general evaluation framework to build your own scorers and
  model-graded rubrics on.** Use **inspect_ai**. It is a framework; this is a
  reliability benchmark with opinions, and those opinions include refusing
  model-graded scoring.

- **You need to watch live production traffic with dashboards and alerting.**
  Use **Langfuse**, **Phoenix** or **Datadog**, and export to them from here.

- **You want a model leaderboard for isolated function-calling accuracy.** Use
  **BFCL**. It does that well and at a scale this project does not attempt.

- **Your agent is a pure text generator with no tools and no side effects.**
  Most of what this measures does not apply. Use a conventional eval harness.

## What this project will not do

Stated because a positioning document that only lists strengths is an
advertisement:

- **No model-graded scoring.** No LLM judges the output. Deterministic
  assertions only, which means some tasks cannot be expressed here at all.
- **No compliance determination.** The evidence dossier assembles facts and
  names the obligations no benchmark can evidence. It never says "compliant".
- **No hosted service.** Self-host it or run it locally. Your data stays yours
  because it never leaves.
- **No claim that the sandbox is a security boundary.** It is a workspace
  boundary with documented limits; see [`threat-model.md`](threat-model.md).
- **No telemetry.** Nothing phones home, and there is no account.

## Verify all of this rather than believing it

Every capability claim in this repository is graded in
[`feature-status.md`](feature-status.md) — including **E** for "works, external
validation blocked" and **N** for "does not exist" — and the table is
machine-checked in CI. So are the README, the CLI reference, and every command
in every documentation code block.

That is the actual differentiator, and it is the one worth checking first: if a
project's documentation is not verified against its code, none of the rest of
its claims can be either.

## Further reading

- [Getting started](getting-started.md) — install, first run, first benchmark
- [Evidence dossier](evidence-dossier.md) — what it records and what it refuses
- [Security evaluation](security-evaluation.md) — the injection suite and its limits
- [Scoring production traces](production-traces.md) — OTel GenAI in, scores out
- [Statistical policy](statistics.md) — which estimator, and why
- [Competitive analysis](competitive-analysis.md) — 26 projects, generated from fetched data
