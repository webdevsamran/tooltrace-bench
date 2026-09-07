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
