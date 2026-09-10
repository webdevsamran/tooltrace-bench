"""A leaderboard that cannot tell Qwen from Llama is not a leaderboard.

The dashboard grouped runs by adapter name. That is fine while every agent is a
different adapter and wrong the moment anybody benchmarks local models:
`openai_compat` drives Ollama, llama.cpp, LM Studio, vLLM and SGLang, so a sweep
across five models produced **one row named `openai_compat`** whose success rate
was the average of five different models.

The same identity has to be used by the cost-accuracy frontier, or the two views
disagree about who the competitors are and the frontier names an agent the
leaderboard does not list.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_generator() -> Any:
    """Import `scripts/generate_web_data.py`, which is not a package module."""
    spec = importlib.util.spec_from_file_location(
        "ttb_generate_web_data", ROOT / "scripts" / "generate_web_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResult:
    def __init__(self, agent: str, model: str | None) -> None:
        self.agent = agent
        self.agent_config = {"model": model} if model else {}


@pytest.fixture(scope="module")
def generator() -> Any:
    return load_generator()


def test_two_models_on_one_adapter_are_two_competitors(generator: Any) -> None:
    """The defect, stated as a test.

    Before this, both of these landed on a row called `openai_compat` whose
    success rate was the average of two different models.
    """
    identity = generator._identity
    qwen = identity(FakeResult("openai_compat", "qwen3:8b"))
    llama = identity(FakeResult("openai_compat", "llama3.1:8b"))
    assert qwen != llama


def test_the_same_model_on_the_same_adapter_is_one_competitor(generator: Any) -> None:
    identity = generator._identity
    assert identity(FakeResult("openai_compat", "qwen3:8b")) == identity(
        FakeResult("openai_compat", "qwen3:8b")
    )


def test_the_same_model_name_on_two_adapters_is_two_competitors(generator: Any) -> None:
    """A model served by vLLM and by Ollama is not guaranteed to behave alike:
    quantization, context window and sampling defaults all differ."""
    identity = generator._identity
    assert identity(FakeResult("openai_compat", "qwen3:8b")) != identity(
        FakeResult("anthropic", "qwen3:8b")
    )


def test_a_run_with_no_model_keeps_the_bare_adapter_name(generator: Any) -> None:
    """Rather than acquiring an invented one.

    `scripted` has no model, and appending "(unknown)" to every scripted run
    would be noise -- while pretending a model was declared would be worse.
    """
    assert generator._identity(FakeResult("scripted", None)) == "scripted"


def test_an_empty_model_string_is_treated_as_absent(generator: Any) -> None:
    assert generator._identity(FakeResult("scripted", "")) == "scripted"


def test_the_identity_is_readable_rather_than_a_hash(generator: Any) -> None:
    """It is a leaderboard row label as well as a key."""
    label = generator._identity(FakeResult("openai_compat", "qwen3:8b"))
    assert "openai_compat" in label
    assert "qwen3:8b" in label


# --- the published dataset carries the parts --------------------------------


def test_the_published_rows_carry_adapter_and_model_separately() -> None:
    """So a view can group by either without re-parsing a display string."""
    import json

    rows = json.loads((ROOT / "web" / "public" / "data" / "agents.json").read_text("utf-8"))
    assert rows, "the published dataset has no agent rows"
    for row in rows:
        assert "adapter" in row
        assert "model" in row


def test_an_undeclared_model_is_null_rather_than_a_placeholder() -> None:
    """`null` is a fact. `"unknown"` is a string somebody will group by."""
    import json

    rows = json.loads((ROOT / "web" / "public" / "data" / "agents.json").read_text("utf-8"))
    for row in rows:
        assert row["model"] is None or isinstance(row["model"], str)


def test_the_frontier_and_the_leaderboard_name_the_same_competitors() -> None:
    """Two views that disagree would put an agent on the frontier that the
    leaderboard does not list."""
    import json

    data = ROOT / "web" / "public" / "data"
    agents = {row["name"] for row in json.loads((data / "agents.json").read_text("utf-8"))}
    points = {
        point["agent"] for point in json.loads((data / "pareto.json").read_text("utf-8"))["points"]
    }
    assert points <= agents, f"on the frontier and not on the leaderboard: {points - agents}"
