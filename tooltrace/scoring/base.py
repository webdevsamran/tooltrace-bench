"""Scoring primitives.

A **scorer** is a deterministic, executable check registered under an
assertion type name. It receives the assertion params and the final
workspace path, and returns a :class:`ScorerOutcome` with a score in
``[0, 1]`` plus human-readable detail. No model calls happen here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class ScorerOutcome:
    score: float  # 0.0 .. 1.0
    detail: str = ""


Scorer = Callable[[dict[str, object]], ScorerOutcome]


class ScoringContext(BaseModel):
    """Everything a scorer may need. Kept explicit so scorers stay pure."""

    workspace: str
    task_id: str = ""

    model_config = {"arbitrary_types_allowed": True}


def register_scorer(name: str) -> Callable[[Scorer], Scorer]:
    from tooltrace.core.registry import scorer_registry

    def decorator(fn: Scorer) -> Scorer:
        scorer_registry.register(name)(fn)
        return fn

    return decorator
