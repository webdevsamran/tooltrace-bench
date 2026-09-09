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
