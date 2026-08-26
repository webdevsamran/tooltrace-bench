"""Cohort-safe analysis: comparisons, baselines, trends, snapshots, stats.

Modules:
- ``core``     — cohort compatibility, baselines, trends, paired-run analysis,
                 snapshots, reproducibility scoring, anti-gaming checks.
- ``compare``  — bundle comparison and regression checks.
- ``failures`` — machine-readable failure classification from traces.
- ``stats``    — success/partial rates, recovery, consistency, pass@k/pass^k,
                 Wilson confidence intervals.
"""

from tooltrace.analysis.core import *  # noqa: F403
