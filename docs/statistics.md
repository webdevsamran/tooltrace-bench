# Statistical policy

Which estimator this project uses, when, and why — so a number in a report can
be argued with rather than taken on faith.

## The short version

| Quantity | Estimator | Why |
|---|---|---|
| Success rate | **Wilson** score interval (default) | It is a proportion. Wilson stays inside [0, 1] and behaves at the extremes, where a normal approximation produces intervals that include impossible values. |
| Success rate, alternative | **Bootstrap** (`percentile` / `bca`) | When you want one estimator across every metric, or when runs are known not to be independent Bernoulli draws. |
| Steps, latency | **Bootstrap percentile** | These are not proportions, so Wilson does not apply at all. Before this they had no interval of any kind. |
| Pass/fail stability | **Wald–Wolfowitz runs test** | A rate cannot tell you whether failures are unpredictable or systematic. This can. |

Select with `summarize_reliability(results, ci_method=...)`. The default is
`wilson` and has not changed.

## Why bootstrap for latency

Latency is right-skewed: a handful of slow runs pull the tail out while the
floor stays put. A symmetric interval built from mean ± z·SE understates the
upper tail precisely where the interesting behaviour is. Bootstrapping
resamples the observed data instead of assuming a shape, so a skewed sample
produces a skewed interval.

`percentile` is the default and is unbiased for symmetric statistics. `bca`
(bias-corrected and accelerated) additionally corrects for skew and for the
bootstrap distribution sitting off-centre from the observed statistic; it
costs one extra jackknife pass and is the better choice for small, skewed
samples. Both fall back to percentile quantiles in the degenerate case where
every resample lands on one side of the observed value.

**Fewer than two observations gets no interval — `None`, not a number.** An
interval from a single point would be fabricated, and this project reports
what it could not measure as missing rather than inventing it.

**Bootstrap resampling is seeded.** A benchmark that reports a different
confidence interval each time it runs on identical data is not reproducible,
which is the property this project exists to provide.

## Why a runs test

Two agents can both succeed 60% of the time and be entirely different
propositions:

- one fails unpredictably — retrying might work, might not;
- one reliably fails a particular subset — the rate is stable and the failures
  are diagnosable.

The success rate cannot separate them. The runs test counts *runs* — maximal
blocks of consecutive identical outcomes — and compares that count against
what an independent sequence with the same totals would produce.

- **More runs than expected** (`z > 0`): outcomes alternate more than chance
  allows. The results are unstable; treat any interval over them with
  suspicion.
- **Fewer runs than expected** (`z < 0`): outcomes clump. Something changed
  part-way through — a warming cache, a leaking resource, throttling.
- **`z is None`**: fewer than two of either outcome, so there is no
  independence claim to test. Reported as `None` rather than a made-up number.

`|z| > 1.96` is flagged as flaky, the conventional 5% two-sided threshold.

This matters beyond diagnosis: **every confidence interval on this page
assumes independent runs.** The flakiness block is what tells you whether that
assumption held. An interval over a sequence flagged flaky is not wrong so
much as answering a question you did not ask.

## What is deliberately not here

No p-value is reported for the success rate itself, and no significance test
compares two agents' rates directly. With the small N typical of agent
benchmarking, such a test has very little power, and reporting a
non-significant result invites reading it as evidence of no difference. The
interval is the honest summary: it shows both the estimate and how little the
data constrains it.


## Trajectory metrics in the benchmark summary

`benchmark` reports how an agent reached its score, not only what the score was.
Every run's trace is turned into a trajectory report by
`tooltrace/metrics/aggregate.py`, and the aggregate lands in
`BenchmarkRun.summary` under `trajectory` — both overall and per task — with a
`failure_taxonomy` count alongside it.

| Key | Meaning |
|---|---|
| `efficiency_mean` | Mean score per tool call, per step, per 1k tokens, per second |
| `stagnating_runs` | Runs that repeated a semantically identical call, or cycled between two tools |
| `hallucinated_resource_events` | References to files, tools or commands that do not exist |
| `policy_violating_runs` | Runs with a denied call or an undeclared side effect |
| `unverified_success_runs` | Runs that declared success without running a check after their last mutating call |
| `failure_taxonomy` | How many runs ended in each failure class |
| `failure_steps` | *Where* each failure happened: the seq, the tool, the rule that matched |

**What these do not measure.** They describe the shape of a trajectory, not its
correctness — an agent can take an efficient, non-stagnating, policy-compliant
route to a wrong answer, which is what the scorers are for. `score_per_1k_tokens`
is `null` unless the adapter reports token usage; it is never estimated. The
metrics live in the summary, which is an unversioned dict: they are not part of
the `.tooltrace` bundle format and do not affect `compatibility_key()`, so they
cannot make two bundles incomparable.


## Cost

`benchmark` reports a `cost` block per task and overall, from
`tooltrace/metrics/economics.py`.

| Key | Meaning |
|---|---|
| `cost_per_resolved_task` | Total spend divided by successful runs — what a budget experiences |
| `cost_per_run` | Mean spend per run, priced runs only |
| `total_cost`, `total_tokens` | Sums over the runs that reported them |
| `priced_runs` / `runs` | How much of the picture was measured |
| `currency`, `mixed_currencies` | Two currencies in one summary cannot be added, and say so |

`cost_per_resolved_task` is deliberately not the mean. A failed run spent real
money, so an unreliable agent costs more per resolved task than a reliable one
at the same per-run price — which is the comparison a team is actually making.

**What this does not measure.** Cost appears only when a provider reports it or
a dated price table prices the model; nothing is estimated, interpolated, or
filled in from a typical rate. An adapter that reports no usage produces `null`,
never `0.0`, and the Pareto frontier excludes unpriced agents rather than
ranking them as free.

## Latency is only comparable on comparable hardware

A p95 of 40 ms on a laptop and 40 ms on a GPU server are the same number
describing different things. `environment.json` used to record five fields —
python version, platform string, OS, machine, timestamp — which is enough to know
a run happened on Windows on x86_64 and not enough to know whether its latency
means anything beside another run's.

Every bundle now carries a `hardware` block: CPU count, total memory, GPUs
detected through `nvidia-smi`, and the inference backend **as declared by the
caller**. Nothing in it is guessed. An undetectable value is `null`, and an empty
GPU list is accompanied by `gpu_detection`, which says whether a probe was
possible at all — a machine with an Apple or AMD GPU and no `nvidia-smi` is not a
machine without a GPU. The `WorkerInventory.gpu = False` this replaces is the
failure mode: a hardcoded `False` is indistinguishable from a checked one.

`comparability(a, b)` returns a **three-state verdict**, not a boolean, and that
is the substance of it. A boolean has to lie in one direction: `True` would claim
two runs match when the record never determined their memory size, and `False`
would call two runs from one machine incomparable because neither declared a
backend.

| Verdict | Meaning |
|---|---|
| `comparable` | Everything relevant was determined, and it agrees |
| `not_comparable` | Something relevant was determined, and it differs |
| `unknown` | Nothing differs, but something was never determined |

Differences are returned as both values, because "not comparable" is not
actionable and "8 CPUs versus 64" is. This deliberately does **not** fold into
`compatibility_key`: that key gates whether artifacts can be *read* together,
which has one right answer. Hardware difference is a caveat on interpretation,
and refusing to compare two runs from different laptops would break the tool for
its most common use.

## Where the wall time went

`model_ms` and `tool_ms` were recorded on every result and never reported
together, so a reader could see that a run took 40 ms and not whether the agent
was slow at deciding or slow at acting — the first question anyone optimising an
agent has. `summarize_reliability` now carries a `latency` block with the split
and the harness remainder.

The rule that matters: when an adapter cannot report model time — the scripted
agent has no model at all — the split stays `null` rather than attributing the
remainder to tools, and the aggregate reports `runs_reporting_model_time` so a
split over 2 of 200 runs is not read as a description of those 200. `0.0` and
"not reported" are also kept distinct, because a model that took no measurable
time and an adapter that never said are different facts.

## A pull-request gate that does not fire on noise

`compare` and `regression` take two **single-run** bundles and fail a build when
a metric moves past a threshold. For latency on a deterministic task that is
defensible. For a success rate it is not: one run is one Bernoulli draw, and "the
score dropped from 1.0 to 0.0" describes a coin landing differently. A gate built
on that either blocks pull requests at random or gets switched off, and both are
worse than no gate at all.

`pr-report` compares two *sets* of runs. Two things must both be true before it
fails a build:

1. **The change is real** — the 95% interval on the *difference* excludes zero.
   Not two per-side intervals for a reader to eyeball: overlapping per-side
   intervals do not imply the difference contains zero, and comparing them by eye
   is the most common way to get this wrong.
2. **The change is large enough to matter** — the smallest change the interval
   supports reaches a stated minimum effect. Statistical significance is not
   practical significance. A deterministic task with no run-to-run variance can
   make a 0.1% latency shift *certain*, and failing a pull request on that is
   precisely what gets a gate disabled.

| Verdict | Meaning | Fails the build |
|---|---|---|
| `regressed` | Real, and large enough to matter, in the worse direction | yes |
| `improved` | Real, and large enough to matter, in the better direction | no |
| `no_change_detected` | Either no real change, or a real one too small to matter | no |
| `inconclusive` | Zero is inside the interval, and so is a change that would matter | no |

The fourth verdict is what makes the other three trustworthy. Without it, "no
regression" covers both "we checked" and "we could not tell", so a green check on
3 runs would say the same thing as a green check on 300.

`inconclusive` never fails. Blocking on the absence of evidence would make the
gate a function of how many runs the caller could afford rather than of whether
the code got worse.

Two implementation notes that matter for correctness. Proportions use the
Newcombe difference of Wilson intervals rather than a bootstrap: ten perfect runs
bootstrap to a zero-width interval, and "the rate is exactly 1.0 with no
uncertainty" is the most misleading thing this could report. Latency's minimum
effect is a share of the baseline rather than an absolute figure, because 5 ms is
nothing on a four-second task and everything on a six-millisecond one.

## Deciding how many runs to do, before you do them

Every interval in this project is computed *after* the runs. That leaves the most
consequential decision unsupported: how many runs. People pick 3, or 10, because
they are round numbers, and then read a difference the sample cannot support.

`tooltrace power` answers it beforehand. Two figures are worth stating outright,
because a planner nobody believes is a planner nobody uses:

| Difference to detect | Runs per arm (50% baseline) |
|---|---|
| 20 points | ~99 |
| 10 points | ~393 |
| 5 points | ~1570 |

Two-sided, alpha 0.05, power 0.80, normal approximation to the binomial. A 3-run
sweep does not compare agents; it demonstrates that something runs.

The default baseline rate is **0.5**, deliberately. Variance in a proportion
peaks there, so 0.5 gives the largest -- most conservative -- sample requirement.
Assuming a 0.95 baseline would promise more sensitivity than a sweep delivers,
which is the direction a planner must never err in. And a baseline of exactly 0
or 1 gets no answer at all rather than an infinitely sensitive one: the
approximation does not apply there.

`showdown` now carries this, which is what makes its "not distinguishable at this
sample size" verdict readable. Without a stated minimum detectable effect, that
verdict is indistinguishable from "these agents are the same" -- and they are
opposite claims.

## Is the agent noisy, or is the benchmark broad?

Those two produce the same standard deviation and mean opposite things, and they
have different fixes. `variance_decomposition` splits observed variance in two:

- **Within-configuration** -- the same agent, on the same task, answering
  differently. Nondeterminism.
- **Between-task** -- different tasks producing different rates. The benchmark
  working, not instability.

An agent that is perfect on one task and hopeless on another, entirely
repeatably, has *zero* within-configuration variance. A single standard deviation
calls that flaky. It is not.

The stated limit travels in the output: this **cannot separate the model's
nondeterminism from the harness's**. Both sit inside the within-configuration
term, and separating them needs a fixed-seed control arm that no adapter
currently guarantees. And when there is no variance at all, the share is `null`
rather than `0` -- "none of the variance is noise" and "there was no variance"
are different statements.

## P(A is better than B)

`showdown` also reports a Beta-Binomial posterior. This answers the question
people read a confidence interval as answering anyway; saying it outright is more
honest than letting the misreading do the work.

The prior is uniform Beta(1,1), stated in the output, and is an explicit argument
-- a prior chosen after seeing the data is how a Bayesian analysis becomes a way
to get the answer you wanted. A posterior near 0.5 is reported as *an absence of
evidence in either direction*, never as evidence the two are equal, and below ten
runs per arm the reading says plainly that the prior is doing the work.

## Behaviour a pass/fail score cannot see

The Holistic Agent Leaderboard paper observes that agents with identical accuracy
scores behave very differently, and `recovered: true` is where that shows up
worst -- one field covering three materially different outcomes.

| Grade | What happened |
|---|---|
| `immediate` | Retried the failed tool on the very next call |
| `delayed` | Recovered, after N intervening calls |
| `abandoned` | Never got that tool to succeed again |
| `silently_wrong` | The tool call recovered and the run still failed its assertions |

The last one is the finding a success rate hides: `recovered` is true and the
answer is wrong. The **worst** grade is reported per run rather than the average,
because an agent that recovered from three faults and abandoned a fourth has a
problem a mean would bury.

`error_propagation` answers a related question a count cannot: six failed calls
could be six problems or one problem hit six times. Consecutive failures are
grouped into chains, and a chain of one tool is marked distinctly from a chain
across several.

## Shortcut signals are signals, not verdicts

The research gap is stated as "no way to distinguish genuine capability from
benchmark gaming". That is a request for **evidence**, not for an accusation, and
the failure mode that matters here is not missing a cheat -- it is flagging an
agent that did the work.

So every signal carries what was observed and what a human would have to check,
and the output states outright that these are observations about a trace rather
than findings about an agent. Nothing in it uses the word "cheating".

Three refinements the shipped task packs forced, each of which was a false
positive before it was fixed:

- **A task with an empty starting workspace has nothing to read.** "Create
  src/main.py containing hello" is solved by writing, and flagging it would flag
  it forever.
- **A patch is not a blind write.** `patch_file` names the text it replaces and
  fails when that text is absent, so a successful patch is itself evidence the
  agent knew what was there.
- **`search_text` is reading.** It observes file content, which is the whole
  question being asked.

## What counts as a leaked answer

`leaked_expected_values` searched the objective and the starting workspace
together. Those are different things, and conflating them fired on two correctly
designed tasks.

- The **objective is the specification**. A task that says 'correct the line so
  it reads "status: ready"' has told the agent what to produce; checking that it
  did is the task. Flagging that asks authors to write vaguer objectives, which
  makes tasks worse rather than more rigorous. Reported, never a failure.
- The **starting workspace is input data**. An expected value found there and not
  stated in the objective means a task that looks like a transformation can be
  passed by a copy. This is the only class that fails integrity.
- A **preservation assertion** -- one whose value is already in the file it
  targets, like "implementation untouched" -- is exempt entirely. Flagging it
  would push an author to delete the assertion that stops an agent from "fixing"
  a failing test by rewriting the code beneath it.
