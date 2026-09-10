"""Whether a seed reaches the model, and what it does when it gets there.

`--seed` has only ever shuffled the task subset. Nothing reached the model, so
`variance_decomposition` could report that within-configuration variance covers
"the model's nondeterminism and the harness's together" and could not separate
them -- the fixed-seed control arm its own docstring asks for did not exist.

This is the arm. It is small, and the honest part is the table rather than the
code: a seed means something different at every provider, and three of the five
adapters here cannot use one at all.

The distinction that matters is between **accepted** and **guaranteed**. OpenAI
accepts a `seed` and documents it as best-effort, returning a
`system_fingerprint` that changes when the backend does; identical seeds across
a fingerprint change are not expected to match. Treating that as determinism
would make the control arm silently measure the same thing as the treatment arm,
which is worse than having no control arm: it would produce a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACCEPTED = "accepted"
GUARANTEED = "guaranteed"
UNSUPPORTED = "unsupported"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class SeedSupport:
    adapter: str
    state: str
    #: Where the value goes in the request, or why it goes nowhere.
    field: str
    note: str


SEED_SUPPORT: dict[str, SeedSupport] = {
    "openai_compat": SeedSupport(
        adapter="openai_compat",
        state=ACCEPTED,
        field="seed",
        note=(
            "OpenAI documents `seed` as best-effort and returns a `system_fingerprint` "
            "that changes when the backend does. Local servers (llama.cpp, vLLM, "
            "Ollama) are usually stricter, and are the only place this behaves like a "
            "real control arm"
        ),
    ),
    "gemini": SeedSupport(
        adapter="gemini",
        state=ACCEPTED,
        field="generationConfig.seed",
        note="Accepted and, like OpenAI's, not contractually deterministic",
    ),
    "anthropic": SeedSupport(
        adapter="anthropic",
        state=UNSUPPORTED,
        field="(none)",
        note=(
            "The Messages API has no seed parameter. A fixed-seed arm cannot be built "
            "here, and reporting one would be inventing a control that does not exist"
        ),
    ),
    "scripted": SeedSupport(
        adapter="scripted",
        state=NOT_APPLICABLE,
        field="(no model)",
        note="Deterministic by construction; there is no sampling to hold fixed",
    ),
    "subprocess": SeedSupport(
        adapter="subprocess",
        state=NOT_APPLICABLE,
        field="(opaque)",
        note=(
            "Whatever the child process does with randomness is outside this harness. "
            "Pass the seed through your own command if the agent accepts one"
        ),
    ),
    "streaming": SeedSupport(
        adapter="streaming",
        state=NOT_APPLICABLE,
        field="(opaque)",
        note="Same as subprocess: the child owns its own randomness",
    ),
}


def support_for(adapter: str) -> SeedSupport:
    return SEED_SUPPORT.get(
        adapter,
        SeedSupport(
            adapter=adapter,
            state=UNSUPPORTED,
            field="(unknown)",
            note="not a built-in adapter; seed behaviour is whatever the plugin does",
        ),
    )


def seed_of(agent_config: dict[str, Any] | None) -> int | None:
    """The seed an agent was configured with, or None.

    Read from the recorded config rather than from a separate field, because the
    config is already carried into every bundle -- a second place to record the
    same value is a second place for it to disagree.
    """
    if not agent_config:
        return None
    value = agent_config.get("seed")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def report() -> dict[str, Any]:
    """What a fixed-seed control arm would actually control, per adapter."""
    rows = [
        {
            "adapter": spec.adapter,
            "state": spec.state,
            "field": spec.field,
            "note": spec.note,
        }
        for spec in sorted(SEED_SUPPORT.values(), key=lambda s: s.adapter)
    ]
    usable = [r["adapter"] for r in rows if r["state"] in (ACCEPTED, GUARANTEED)]
    return {
        "adapters": rows,
        "usable": usable,
        "statement": (
            f"{len(usable)} of {len(rows)} adapters pass a seed to the model "
            f"({', '.join(usable)}). None of them guarantee determinism: a seed is "
            "accepted best-effort, so a fixed-seed arm bounds the model's contribution "
            "rather than removing it."
        ),
    }
