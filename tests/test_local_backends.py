"""Local model servers, and the token dimensions nothing was populating.

Ollama, llama.cpp, LM Studio, vLLM and SGLang all speak the OpenAI chat API, so
`openai_compat` already drives every one of them. Writing five adapters would
have added five names to `tooltrace agents` with no new capability behind any of
them — coverage in the listing and none in the code, which is the shape of
overclaiming this repository keeps finding.

What was genuinely missing is smaller and more useful: the ports, the model-name
conventions, and which server is up right now.

The other half of this file is a defect I committed myself. `TokenUsage` grew
`cached_prompt_tokens`, `cache_write_tokens` and `reasoning_tokens`, and
`PriceTable` learned to bill them — and **nothing populated them**, so a
cache-heavy run was still costed at the full input rate. Adding a field and
leaving it unreachable is this project's recurring defect, and it is worth naming
that it happened in the same change that added the fields.
"""

from __future__ import annotations

import json

import pytest
from tooltrace.agents.local_backends import (
    BACKENDS,
    config_for,
    describe,
    detect_running,
    extract_usage,
)
from tooltrace.cli.init import CHOICES, LOCAL_BACKENDS, plan
from tooltrace.cli.main import main
from tooltrace.core.models import TokenUsage

# --- presets, not adapters --------------------------------------------------


def test_every_local_backend_resolves_to_the_shared_adapter(tmp_path) -> None:
    """Five adapters would be five names with no new capability behind them."""
    for backend in LOCAL_BACKENDS:
        got = plan(tmp_path, adapter=backend)
        assert got.adapter == "openai_compat", f"{backend} should not need its own adapter"


def test_each_preset_carries_the_port_a_user_would_otherwise_look_up() -> None:
    assert BACKENDS["ollama"].port == 11434
    assert BACKENDS["lm_studio"].port == 1234
    assert BACKENDS["vllm"].port == 8000


def test_a_config_names_the_backend_for_the_bundle() -> None:
    """Not detectable from inside the harness, so it is recorded as declared."""
    got = config_for("ollama", model="qwen2.5-coder:7b")
    assert got["backend"] == "ollama"
    assert got["base_url"] == "http://localhost:11434/v1"
    assert got["model"] == "qwen2.5-coder:7b"


def test_server_side_flags_can_be_declared_because_nothing_can_detect_them() -> None:
    got = config_for("vllm", model="m", quantization="awq", engine_version="0.6.3")
    assert got["quantization"] == "awq"
    assert got["engine_version"] == "0.6.3"


def test_no_api_key_value_is_ever_placed_in_a_config() -> None:
    got = config_for("ollama", api_key_env="MY_KEY")
    assert got["api_key_env"] == "MY_KEY"
    assert "api_key" not in got


def test_an_unknown_backend_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        config_for("not-a-server")


def test_every_preset_warns_about_its_own_footgun() -> None:
    """A preset that hands over a URL and says nothing else is half the help."""
    for spec in BACKENDS.values():
        assert spec.note, f"{spec.name} has no note"
    assert "pin the tag" in BACKENDS["ollama"].note
    assert "ignores the `model` field" in BACKENDS["llama_cpp"].note


# --- detection --------------------------------------------------------------


def test_detection_reports_what_a_port_probe_can_and_cannot_establish() -> None:
    """An open port is not a positive identification of the server."""
    for row in detect_running():
        assert "not a positive identification" in row["evidence"]


def test_detection_only_ever_looks_at_localhost(monkeypatch) -> None:
    """The one place this project opens a socket by default."""
    seen: list[tuple] = []

    def record(address, timeout=None):
        seen.append(address)
        raise OSError("refused")

    monkeypatch.setattr("tooltrace.agents.local_backends.socket.create_connection", record)
    detect_running()
    assert seen, "nothing was probed"
    assert {host for host, _port in seen} == {"127.0.0.1"}


def test_nothing_listening_reports_nothing_rather_than_guessing(monkeypatch) -> None:
    monkeypatch.setattr("tooltrace.agents.local_backends._port_open", lambda *a, **k: False)
    assert detect_running() == []
    assert describe()["listening"] == []


def test_the_description_states_why_there_are_no_extra_adapters() -> None:
    assert "rather than five adapters" in describe()["statement"]
    assert "nothing leaves this machine" in describe()["statement"]


# --- token dimensions across provider shapes --------------------------------


def test_openai_style_nested_details_are_read() -> None:
    got = extract_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 80},
            "completion_tokens_details": {"reasoning_tokens": 15},
        }
    )
    assert got["cached_prompt_tokens"] == 80
    assert got["reasoning_tokens"] == 15


def test_anthropic_style_top_level_fields_are_read() -> None:
    got = extract_usage(
        {"prompt_tokens": 100, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 10}
    )
    assert got["cached_prompt_tokens"] == 80
    assert got["cache_write_tokens"] == 10


def test_a_server_that_reports_none_of_it_yields_none_not_zero() -> None:
    """Zero cached tokens and no information about caching bill identically and
    mean different things."""
    got = extract_usage({"prompt_tokens": 100, "completion_tokens": 20})
    assert got["cached_prompt_tokens"] is None
    assert got["reasoning_tokens"] is None
    assert got["prompt_tokens"] == 100


def test_a_negative_or_nonsense_count_is_dropped() -> None:
    got = extract_usage({"prompt_tokens": -5, "completion_tokens": "many"})
    assert got["prompt_tokens"] is None
    assert got["completion_tokens"] is None


def test_the_extracted_shape_matches_the_model_fields() -> None:
    """A key here that `TokenUsage` does not have would be silently dropped."""
    got = extract_usage({"prompt_tokens": 1})
    assert set(got) <= set(TokenUsage.model_fields)


# --- accumulation across turns ----------------------------------------------


def test_accumulating_keeps_never_reported_distinct_from_zero() -> None:
    """The old accumulator coerced None to 0, so a provider that says nothing
    about caching became indistinguishable from one reporting none."""
    from tooltrace.agents.openai_compat import _add

    assert _add(None, None) is None
    assert _add(None, 5) == 5
    assert _add(5, None) == 5
    assert _add(5, 5) == 10


def test_a_cache_heavy_run_is_billed_at_the_cached_rate() -> None:
    """The end-to-end point of the whole change: the fields reach the price table."""
    from tooltrace.agents.interop import PriceTable

    table = PriceTable.model_validate(
        {
            "prices": {
                "m": [
                    {
                        "input_per_1k": 1.0,
                        "output_per_1k": 3.0,
                        "cached_input_per_1k": 0.1,
                        "effective_from": "2026-01-01",
                    }
                ]
            }
        }
    )
    reported = extract_usage(
        {
            "prompt_tokens": 10_000,
            "completion_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 9_000},
        }
    )
    cost = table.compute_cost(
        "m",
        reported["prompt_tokens"] or 0,
        reported["completion_tokens"] or 0,
        "2026-09-09",
        cached_input_tokens=reported["cached_prompt_tokens"] or 0,
    )
    assert cost["cost"] == pytest.approx(1.9)
    # Without the plumbing this would have been 10.0.
    assert cost["cost"] < 10.0


# --- the CLI ----------------------------------------------------------------


def test_the_backends_command_lists_every_preset(capsys) -> None:
    assert main(["backends", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {row["backend"] for row in payload["backends"]} == set(BACKENDS)


def test_init_accepts_a_backend_by_name(tmp_path, capsys) -> None:
    """Knowing that Ollama is on 11434 is exactly the friction this removes."""
    assert main(["init", "--dir", str(tmp_path), "--agent", "ollama", "--no-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan"]["adapter"] == "openai_compat"
    assert payload["plan"]["agent_config"]["base_url"] == "http://localhost:11434/v1"


def test_init_warns_when_the_server_is_not_running(tmp_path, monkeypatch) -> None:
    """ "The server is down" and "the agent failed" both score zero."""
    monkeypatch.setattr("tooltrace.agents.local_backends._port_open", lambda *a, **k: False)
    got = plan(tmp_path, adapter="ollama")
    assert any("nothing is listening" in note for note in got.notes)


def test_init_does_not_warn_when_it_is_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tooltrace.agents.local_backends._port_open", lambda *a, **k: True)
    got = plan(tmp_path, adapter="ollama")
    assert not any("nothing is listening" in note for note in got.notes)


def test_every_choice_is_offered_by_init() -> None:
    assert set(CHOICES) >= set(LOCAL_BACKENDS)
    assert "scripted" in CHOICES
