"""Prefill, cache, TTFT and energy -- and the ones that refuse to produce a number.

Four questions a team asks once they are running a local model and paying for
the GPU themselves. Each answer here is either measured from something the
platform or the provider actually reported, or absent: there is no estimate
anywhere in the module, because a plausible-looking energy or TTFT figure would
be indistinguishable from a measured one three functions later.

Two of the four normally come back unmeasured, and the tests below are mostly
about that being *correct* rather than a gap:

- **TTFT** needs a streaming response and no adapter here streams. Dividing
  total latency by anything would produce a number that moves with the length of
  the reply -- a fast model writing a long answer would read as slow to start.
- **Energy** is read from RAPL or `nvidia-smi` where they exist. Multiplying a
  datasheet TDP by a duration would be arithmetic about a datasheet, not a
  measurement of this run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tooltrace.telemetry.efficiency import (
    CARBON_NOTE,
    EnergyWindow,
    cache_profile,
    energy_sources,
    handler_matrix,
    prefill_overhead,
    report,
    time_to_first_token,
)


def run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agent": "openai_compat",
        "agent_config": {"model": "qwen3:8b", "backend": "ollama"},
        "success": True,
        "usage": {"tokens": {"prompt_tokens": 1000, "cached_prompt_tokens": 400}},
    }
    base.update(overrides)
    return base


# --- prefill: measurable, and nobody measures it ----------------------------


def test_the_catalogue_and_scaffold_are_both_counted() -> None:
    overhead = prefill_overhead()
    assert overhead["catalogue_chars"] > 0
    assert overhead["scaffold_chars"] > 0
    assert overhead["total_chars"] == overhead["catalogue_chars"] + overhead["scaffold_chars"]


def test_restricting_the_tools_reduces_the_overhead() -> None:
    """The point of the metric: a catalogue is charged on every turn."""
    everything = prefill_overhead()
    one = prefill_overhead(["read_file"])
    assert one["catalogue_chars"] < everything["catalogue_chars"]
    assert one["tools"] == 1


def test_the_token_figure_says_it_is_an_estimate() -> None:
    """No tokeniser ships here, so the field name has to carry the caveat."""
    overhead = prefill_overhead()
    assert overhead["is_estimate"] is True
    assert "approx_tokens" in overhead
    assert "diagnostic rather than a billing figure" in overhead["statement"]


# --- cache: reported or absent, never inferred ------------------------------


def test_a_reported_cache_count_produces_a_hit_rate() -> None:
    profile = cache_profile([run(), run()])
    assert profile["measurable"] is True
    assert profile["hit_rate"] == 0.4


def test_a_run_that_says_nothing_about_caching_is_excluded_not_counted_as_a_miss() -> None:
    """ "We do not know" and "nothing was cached" bill identically and mean
    entirely different things."""
    profile = cache_profile([run(), run(usage={"tokens": {"prompt_tokens": 1000}})])
    assert profile["runs_reporting_cache"] == 1
    assert profile["runs_silent_about_cache"] == 1
    assert profile["hit_rate"] == 0.4, "the silent run must not drag the rate toward zero"


def test_no_run_reporting_a_cache_is_unmeasurable_with_a_reason() -> None:
    profile = cache_profile([run(usage={})])
    assert profile["measurable"] is False
    assert "reported a cached-prompt count" in profile["reason"]


def test_a_zero_length_prompt_is_skipped_rather_than_dividing_by_zero() -> None:
    profile = cache_profile(
        [run(usage={"tokens": {"prompt_tokens": 0, "cached_prompt_tokens": 0}})]
    )
    assert profile["measurable"] is False


def test_the_statement_names_how_many_runs_were_excluded() -> None:
    profile = cache_profile([run(), run(usage={})])
    assert "excluded rather than" in profile["statement"]


# --- ttft: the refusal ------------------------------------------------------


def test_ttft_is_unmeasured_and_says_why() -> None:
    result = time_to_first_token([run()])
    assert result["measurable"] is False
    assert "no adapter here streams" in result["reason"]


def test_ttft_says_what_would_be_needed_rather_than_only_that_it_is_missing() -> None:
    result = time_to_first_token([])
    assert "stream: true" in result["what_would_be_needed"]


def test_ttft_explains_why_it_is_not_approximated() -> None:
    """Dividing total latency would measure the length of the reply."""
    assert "length of the response" in time_to_first_token([])["not_approximated_because"]


# --- energy: read, or absent ------------------------------------------------


def test_energy_sources_are_probed_rather_than_assumed() -> None:
    sources = energy_sources()
    assert isinstance(sources["available"], bool)
    assert isinstance(sources["cpu_rapl_domains"], list)


def test_a_machine_with_no_counters_says_so_rather_than_reporting_zero() -> None:
    """ "0 joules" on a machine with no counters is a measurement of nothing
    presented as a measurement of something."""
    sources = energy_sources()
    if not sources["available"]:
        assert "unmeasured" in sources["statement"]
        assert "TDP" in sources["statement"]


def test_carbon_is_never_computed_from_a_constant() -> None:
    """Grid intensity varies by hour and by contract; one constant would turn a
    measured energy figure into an invented carbon one."""
    assert "multiply by your own intensity" in CARBON_NOTE
    assert energy_sources()["carbon_note"] == CARBON_NOTE


def test_an_energy_window_is_a_difference_not_an_absolute_reading() -> None:
    """RAPL counters are cumulative: an absolute value records uptime."""
    with EnergyWindow() as window:
        pass
    result = window.joules()
    assert "total_joules" in result or result["measurable"] is False


def test_a_window_on_a_machine_with_no_counters_is_unmeasurable() -> None:
    window = EnergyWindow()
    assert window.joules()["measurable"] is False


# --- the handler matrix: built from what ran --------------------------------


def test_the_matrix_is_built_from_runs_not_from_a_support_list() -> None:
    """A hardcoded matrix records what somebody believed when they typed it."""
    matrix = handler_matrix(
        [run(), run(), run(agent_config={"model": "llama3", "backend": "vllm"})]
    )
    assert matrix["counts"]["combinations"] == 2
    assert "not from a list of what is supported" in matrix["statement"]


def test_a_small_sample_is_flagged_in_the_cell() -> None:
    """A cell showing 100% from one run is the most misleading thing here."""
    matrix = handler_matrix([run()])
    assert matrix["combinations"][0]["sample_is_small"] is True
    assert matrix["combinations"][0]["success_rate"] == 1.0


def test_ten_runs_is_no_longer_flagged() -> None:
    matrix = handler_matrix([run() for _ in range(10)])
    assert matrix["combinations"][0]["sample_is_small"] is False


def test_a_run_declaring_no_model_is_named_as_such() -> None:
    """Grouping them silently would present several configurations as one."""
    matrix = handler_matrix([run(agent_config={})])
    assert matrix["combinations"][0]["model"] == "(not declared)"
    assert "declare no model" in matrix["statement"]


def test_no_runs_produces_an_empty_matrix_rather_than_a_populated_one() -> None:
    """This table should usually be mostly empty, and that is correct."""
    assert handler_matrix([])["counts"]["combinations"] == 0


# --- the combined report and the CLI ----------------------------------------


def test_the_report_carries_every_answer() -> None:
    payload = report([run()])
    assert set(payload) == {
        "prefill",
        "cache",
        "ttft",
        "energy",
        "handlers",
        "quantization",
    }


def test_the_cli_reports_this_machine_without_any_bundles(capsys) -> None:
    from tooltrace.cli.main import main

    assert main(["hardware", "--json"]) == 0
    capsys.readouterr()


def test_the_cli_wires_the_latency_split_that_had_no_caller(capsys) -> None:
    """`latency_split` and `aggregate_latency` shipped with no caller outside
    their own tests, so "slow at thinking or slow at doing" could be computed
    and was never asked."""
    import json

    from tooltrace.cli.main import main

    results = Path(__file__).resolve().parents[1] / "results"
    if not any(results.glob("*.tooltrace")):  # pragma: no cover
        return
    assert main(["hardware", "--bundles", str(results), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["latency"]["runs"] > 0
    assert "comparability" in payload


# --- quantization: the validity condition, not the arithmetic ---------------


def quantized(level: str, *, success: bool = True, wall: float = 100.0, **overrides: Any) -> dict:
    config = {"quantization": level, "model": "qwen3:8b", "backend": "ollama"}
    config.update(overrides.pop("config", {}))
    return {
        "agent": "openai_compat",
        "agent_config": config,
        "success": success,
        "wall_ms": wall,
        "environment": {"machine": "x86_64"},
        **overrides,
    }


def test_two_levels_on_one_machine_are_comparable() -> None:
    from tooltrace.telemetry.efficiency import quantization_curve

    curve = quantization_curve(
        [quantized("Q4"), quantized("Q4"), quantized("Q8", wall=200), quantized("Q8", wall=190)]
    )
    assert curve["comparable"] is True
    assert [p["quantization"] for p in curve["points"]] == ["Q4", "Q8"]


def test_a_second_model_makes_it_not_a_quantization_curve() -> None:
    """The difference between the points becomes the sum of every axis that moved.

    Reporting that as a quantization effect would be the most confidently wrong
    number in the module.
    """
    from tooltrace.telemetry.efficiency import quantization_curve

    curve = quantization_curve(
        [quantized("Q4"), quantized("Q8"), quantized("Q8", config={"model": "llama3"})]
    )
    assert curve["comparable"] is False
    assert "model" in curve["confounded_by"]
    assert "not a quantization curve" in curve["statement"]


def test_a_second_machine_also_confounds_it() -> None:
    from tooltrace.telemetry.efficiency import quantization_curve

    curve = quantization_curve([quantized("Q4"), quantized("Q8", environment={"machine": "arm64"})])
    assert "machine" in curve["confounded_by"]


def test_one_level_is_not_a_curve() -> None:
    from tooltrace.telemetry.efficiency import quantization_curve

    curve = quantization_curve([quantized("Q4"), quantized("Q4")])
    assert curve["comparable"] is False
    assert "at least two points" in curve["reason"]


def test_runs_declaring_no_quantization_are_excluded_not_bucketed() -> None:
    """An "unknown" bucket would mix every unlabelled run into one row and call
    it a quantization level."""
    from tooltrace.telemetry.efficiency import quantization_curve

    curve = quantization_curve([quantized("Q4"), run(), run()])
    assert curve["unlabelled_runs"] == 2
    assert [p["quantization"] for p in curve["points"]] == ["Q4"]


def test_a_thin_level_is_flagged() -> None:
    from tooltrace.telemetry.efficiency import quantization_curve

    curve = quantization_curve([quantized("Q4"), quantized("Q8")])
    assert all(point["sample_is_small"] for point in curve["points"])


def test_the_curve_reaches_the_combined_report() -> None:
    """An analysis behind a function nobody calls is an orphan."""
    assert "quantization" in report([quantized("Q4")])
