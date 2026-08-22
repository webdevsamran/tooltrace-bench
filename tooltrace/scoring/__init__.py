"""Deterministic scoring. Importing this package registers built-in scorers."""

from tooltrace.scoring.base import ScorerOutcome, register_scorer
from tooltrace.scoring.builtin import *  # noqa: F403
from tooltrace.scoring.composite import is_partial_success, is_success, score_task

__all__ = [
    "ScorerOutcome",
    "is_partial_success",
    "is_success",
    "register_scorer",
    "score_task",
]
