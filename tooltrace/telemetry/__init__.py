"""Telemetry: timing, token usage and cost collection.

Public surface for the reliability metrics pipeline. The implementations live
in :mod:`tooltrace.stats` (aggregation) and :mod:`tooltrace.core.models`
(usage metadata); this package exposes them under the documented
``tooltrace.telemetry`` namespace so integrations have a stable import path.
"""

from __future__ import annotations

from tooltrace.analysis.stats import (
    consistency,
    mean,
    p50,
    p95,
    percentile,
    recovery_rate,
    success_rate,
    summarize_reliability,
    wilson_interval,
)
from tooltrace.core.models import UsageMetadata

__all__ = [
    "UsageMetadata",
    "consistency",
    "mean",
    "p50",
    "p95",
    "percentile",
    "recovery_rate",
    "success_rate",
    "summarize_reliability",
    "wilson_interval",
]
