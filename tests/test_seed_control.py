"""The fixed-seed control arm `variance_decomposition` said did not exist.

`--seed` had only ever shuffled the task subset. Nothing reached the model, so
within-configuration variance covered the model's nondeterminism and the
harness's together and the docstring said, correctly, that separating them
needed a control arm no adapter provided.

This is that arm, and the honest half of it is the table rather than the
arithmetic. A seed means something different at every provider, three of the six
adapters here cannot use one at all, and **none of them guarantee determinism**:
OpenAI documents `seed` as best-effort behind a `system_fingerprint` that changes
with the backend. Treating "accepted" as "guaranteed" would make the control arm
silently measure the same thing as the treatment arm, which is worse than having
no control arm because it would produce a number.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from tooltrace.agents.gemini import GeminiAgent
from tooltrace.agents.openai_compat import OpenAICompatAgent
from tooltrace.agents.seeds import (
    GUARANTEED,
    NOT_APPLICABLE,
    SEED_SUPPORT,
    UNSUPPORTED,
    report,
    seed_of,
    support_for,
)
from tooltrace.analysis.power import variance_decomposition
from tooltrace.core.models import AgentContext
from tooltrace.core.registry import agent_registry

FINISH = json.dumps({"action": "finish", "message": "done"})


# --- the table --------------------------------------------------------------


def test_no_adapter_claims_a_guaranteed_seed() -> None:
    """The claim nobody can make.

    A provider that documents `seed` as best-effort has not promised
    determinism, and recording that promise here would make every downstream
    number wrong in the same direction.
    """
    assert all(spec.state != GUARANTEED for spec in SEED_SUPPORT.values())


def test_anthropic_is_unsupported_rather_than_quietly_ignored() -> None:
    """The Messages API has no seed parameter at all."""
    assert support_for("anthropic").state == UNSUPPORTED
    assert "no seed parameter" in support_for("anthropic").note


def test_an_agent_with_no_model_is_not_applicable_rather_than_unsupported() -> None:
    """`scripted` is deterministic by construction; there is nothing to hold fixed.

    Calling that "unsupported" would read as a gap to close.
    """
    for adapter in ("scripted", "subprocess", "streaming"):
        assert support_for(adapter).state == NOT_APPLICABLE


def test_an_unknown_adapter_is_described_rather_than_raising() -> None:
    spec = support_for("some-plugin")
    assert spec.state == UNSUPPORTED
    assert "plugin" in spec.note


def test_every_built_in_adapter_is_in_the_table() -> None:
    """A registered adapter missing here has undocumented seed behaviour."""
    for name in agent_registry.names():
        assert name in SEED_SUPPORT, f"{name} has no declared seed behaviour"


def test_the_summary_says_a_seed_bounds_rather_than_isolates() -> None:
    assert "bounds the model's contribution rather than removing it" in report()["statement"]


# --- the seed actually reaches the request ----------------------------------


class Recorder:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.body: dict[str, Any] = {}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        class FakeResponse:
            def raise_for_status(self) -> None: ...

            def json(self) -> dict[str, Any]:
                return recorder.reply

        class FakeClient:
            def __init__(self, *a: object, **k: object) -> None: ...

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *a: object) -> bool:
                return False

            def post(self, url: str, **kwargs: Any) -> FakeResponse:
                recorder.body = kwargs.get("json") or {}
                return FakeResponse()

        monkeypatch.setattr(httpx, "Client", FakeClient)


def context() -> AgentContext:
    return AgentContext(task_id="p/one", objective="do it", description="", allowed_tools=[])


def test_openai_sends_the_seed_when_one_is_configured(monkeypatch) -> None:
    recorder = Recorder({"choices": [{"message": {"content": FINISH}}]})
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://x/v1", "seed": 7})
    agent.initialize(context())
    agent.act(0, [])
    assert recorder.body["seed"] == 7


def test_openai_omits_the_field_entirely_when_no_seed_is_set(monkeypatch) -> None:
    """Some OpenAI-compatible servers reject `"seed": null`.

    Sending it unconditionally would make configuring nothing worse than
    configuring something.
    """
    recorder = Recorder({"choices": [{"message": {"content": FINISH}}]})
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://x/v1"})
    agent.initialize(context())
    agent.act(0, [])
    assert "seed" not in recorder.body


def test_gemini_puts_the_seed_where_gemini_reads_it(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    recorder = Recorder({"candidates": [{"content": {"parts": [{"text": FINISH}]}}]})
    recorder.install(monkeypatch)
    agent = GeminiAgent(config={"seed": 11})
    agent.initialize(context())
    agent.act(0, [])
    assert recorder.body["generationConfig"]["seed"] == 11
    assert "seed" not in recorder.body


def test_a_boolean_is_not_a_seed() -> None:
    """`True` is an `int` in Python, and `"seed": true` is not a seed."""
    assert seed_of({"seed": True}) is None
    assert seed_of({"seed": 0}) == 0
    assert seed_of({}) is None
    assert seed_of(None) is None


# --- the variance split -----------------------------------------------------


def runs(seed: int | None, outcomes: list[bool], task: str = "t") -> list[dict[str, Any]]:
    config = {"seed": seed} if seed is not None else {}
    return [
        {"agent": "a", "task_id": task, "success": ok, "agent_config": dict(config)}
        for ok in outcomes
    ]


def test_unseeded_runs_report_why_the_split_is_impossible() -> None:
    report_ = variance_decomposition(runs(None, [True, False, True, False]))
    assert report_["seeded"]["measurable"] is False
    assert "carried no seed at all" in report_["seeded"]["reason"]


def test_variance_within_one_seed_is_attributed_to_the_harness() -> None:
    """The model is held as fixed as the provider allows, so what moves is not it."""
    report_ = variance_decomposition(runs(1, [True, False, True, False]))
    assert report_["seeded"]["measurable"] is True
    assert report_["seeded"]["harness_and_machine_variance"] > 0


def test_a_deterministic_harness_at_one_seed_reports_zero_and_no_model_term() -> None:
    """One seed cannot say anything about the model's sampling.

    Reporting 0 there would claim the model contributed nothing, when the truth
    is that nobody varied the seed.
    """
    report_ = variance_decomposition(runs(1, [True, True, True, True]))
    assert report_["seeded"]["harness_and_machine_variance"] == 0
    assert report_["seeded"]["model_sampling_variance"] is None


def test_variance_across_seeds_is_attributed_to_the_model() -> None:
    stable_within = runs(1, [True, True]) + runs(2, [False, False])
    report_ = variance_decomposition(stable_within)
    assert report_["seeded"]["harness_and_machine_variance"] == 0
    assert report_["seeded"]["model_sampling_variance"] is not None
    assert report_["seeded"]["model_sampling_variance"] > 0


def test_seeded_and_unseeded_runs_coexist_and_the_count_is_reported() -> None:
    mixed = runs(1, [True, True]) + runs(None, [False, False])
    seeded = variance_decomposition(mixed)["seeded"]
    assert seeded["measurable"] is True
    assert seeded["unseeded_runs"] == 2
    assert seeded["runs"] == 2


def test_the_split_carries_its_own_caveat() -> None:
    """A number without the caveat would read as an exact attribution."""
    seeded = variance_decomposition(runs(1, [True, False]))["seeded"]
    assert "bounds" in seeded["caveat"]


def test_the_split_arrives_without_a_second_call() -> None:
    """An analysis behind a function nobody remembers to call is an orphan.

    This repository has shipped several; the split is returned by the existing
    entry point rather than beside it.
    """
    assert "seeded" in variance_decomposition(runs(1, [True, False]))


def test_a_single_run_still_reports_the_outer_decomposition_as_unmeasurable() -> None:
    report_ = variance_decomposition(runs(1, [True]))
    assert report_["measurable"] is False
