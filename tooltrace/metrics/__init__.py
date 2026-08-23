"""Trajectory reliability metrics (Prompt-2 features 31-46).

All functions are pure and deterministic; they operate on EvalResult-like
dicts/objects so they can be applied to bundles, traces or live results.
"""

from tooltrace.metrics.policy import (
    change_minimality,
    policy_compliance,
    side_effect_correctness,
)
from tooltrace.metrics.reliability import (
    bootstrap_ci,
    effect_size_cohens_h,
    paired_delta,
    pass_at_k,
    pass_hat_k,
    significance_note,
)
from tooltrace.metrics.trajectory import (
    confusion_matrix,
    context_retention,
    efficiency_metrics,
    hallucinated_resources,
    loop_detection,
    verification_quality,
)

__all__ = [
    "bootstrap_ci",
    "change_minimality",
    "confusion_matrix",
    "context_retention",
    "effect_size_cohens_h",
    "efficiency_metrics",
    "hallucinated_resources",
    "loop_detection",
    "paired_delta",
    "pass_at_k",
    "pass_hat_k",
    "policy_compliance",
    "side_effect_correctness",
    "significance_note",
    "verification_quality",
]
