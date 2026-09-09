"""Hardware metadata exists to answer one question: are these two numbers comparable?

`environment.json` recorded python version, platform, OS, machine and a
timestamp. That is enough to know a run happened on Windows on x86_64, and not
enough to know whether its latency means anything beside another run's. A p95 of
40 ms on a laptop and 40 ms on a GPU server are the same number describing
different things, and a leaderboard that ranks them together measures the
hardware while claiming to measure the agent.

The recurring hazard in a module like this is the plausible default. The old
`WorkerInventory.gpu = False` is the example: a hardcoded `False` is
indistinguishable from "checked, and there is no GPU". So the rules these tests
enforce are that an undetectable value is `None`, that an empty GPU list says
whether a probe was even possible, that a declared value is labelled as declared,
and that two runs with unknown fields are never reported as known to match.

The latency split has the same shape. `model_ms` and `tool_ms` were on every
result and nothing reported them together, so nobody could tell a slow-thinking
agent from a slow-acting one. When an adapter cannot report model time, the split
must stay unknown rather than attributing the remainder to tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.telemetry.hardware import (
    PROFILE_FIELDS,
    aggregate_latency,
    comparability,
    declared_backend,
    detect_gpus,
    gpu_detection,
    hardware_metadata,
    hardware_profile,
    latency_split,
)

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"


def env(**hardware: object) -> dict:
    base = {
        "cpu_count": 8,
        "cpu": "test cpu",
        "memory_gb": 16.0,
        "gpus": [],
        "gpu_detection": "probed",
        "inference": declared_backend(None),
    }
    base.update(hardware)
    return {"os": "Linux", "machine": "x86_64", "hardware": base}


# --- nothing is guessed -----------------------------------------------------


def test_an_empty_gpu_list_says_whether_a_probe_was_possible() -> None:
    """The distinction the old hardcoded `gpu = False` erased."""
    assert gpu_detection() in {"probed", "not_detectable"}


def test_no_probe_means_not_detectable_not_no_gpu(monkeypatch) -> None:
    monkeypatch.setattr("tooltrace.telemetry.hardware.shutil.which", lambda _: None)
    assert detect_gpus() == []
    assert gpu_detection() == "not_detectable"


def test_a_failing_probe_does_not_crash_the_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "tooltrace.telemetry.hardware.shutil.which", lambda _: "/usr/bin/nvidia-smi"
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no such thing")

    monkeypatch.setattr("tooltrace.telemetry.hardware.subprocess.run", boom)
    assert detect_gpus() == []


def test_gpu_parsing_survives_junk(monkeypatch) -> None:
    class Proc:
        returncode = 0
        stdout = "GPU One, notanumber, 1.2\n\n, 4096, 1.2\nGPU Two, 8192, 3.4\n"

    monkeypatch.setattr("tooltrace.telemetry.hardware.shutil.which", lambda _: "nvidia-smi")
    monkeypatch.setattr("tooltrace.telemetry.hardware.subprocess.run", lambda *a, **k: Proc())
    gpus = detect_gpus()
    assert [g["name"] for g in gpus] == ["GPU One", "GPU Two"]
    # An unparseable VRAM figure is None, not 0: zero VRAM is a claim.
    assert gpus[0]["vram_mb"] is None
    assert gpus[1]["vram_mb"] == 8192


def test_an_undetectable_memory_size_is_none(monkeypatch) -> None:
    """On Windows there is no dependency-free way to ask. None, not a guess."""
    # `raising=False`: os.sysconf does not exist on Windows at all, which is
    # itself one of the paths this must survive.
    monkeypatch.setattr(
        "tooltrace.telemetry.hardware.os.sysconf",
        lambda _: (_ for _ in ()).throw(ValueError("nope")),
        raising=False,
    )
    from tooltrace.telemetry.hardware import total_memory_gb

    assert total_memory_gb() is None


# --- declared versus detected -----------------------------------------------


def test_an_undeclared_backend_says_so() -> None:
    declared = declared_backend(None)
    assert declared["is_declared"] is False
    assert declared["source"] == "declared_by_caller"


def test_a_declared_backend_is_labelled_as_declared() -> None:
    """The harness cannot detect any of this, and must not imply that it did."""
    declared = declared_backend({"backend": "vllm", "quantization": "awq", "model": "qwen"})
    assert declared["is_declared"] is True
    assert declared["backend"] == "vllm"
    assert declared["source"] == "declared_by_caller"


def test_empty_declarations_read_as_not_stated() -> None:
    assert declared_backend({"backend": "", "model": ""})["is_declared"] is False


def test_no_api_key_reaches_the_metadata() -> None:
    """A config can carry a secret. `environment.json` is published."""
    metadata = hardware_metadata({"api_key": "sk-secret", "base_url": "http://x"})
    assert "sk-secret" not in json.dumps(metadata)


def test_the_metadata_block_has_the_fields_a_reader_needs() -> None:
    metadata = hardware_metadata(None)
    for field in ("cpu_count", "memory_gb", "gpus", "gpu_detection", "inference"):
        assert field in metadata


# --- comparability ----------------------------------------------------------


def test_two_identical_fully_determined_machines_are_comparable() -> None:
    verdict = comparability(
        env(inference={**declared_backend({"backend": "vllm"})}),
        env(inference={**declared_backend({"backend": "vllm"})}),
    )
    assert verdict["verdict"] == "comparable"
    assert verdict["differences"] == {}


def test_a_different_cpu_count_is_reported_with_both_values() -> None:
    """ "Not comparable" is not actionable. "8 versus 64 CPUs" is."""
    verdict = comparability(env(cpu_count=8), env(cpu_count=64))
    assert verdict["verdict"] == "not_comparable"
    assert verdict["differences"]["cpu_count"] == [8, 64]


def test_a_gpu_on_one_side_only_is_a_difference() -> None:
    verdict = comparability(env(gpus=[{"name": "A100"}]), env(gpus=[]))
    assert "gpu_names" in verdict["differences"]


def test_an_unknown_field_is_reported_as_unknown_not_as_a_match() -> None:
    """The reason the verdict is three-state.

    Two runs that both failed to detect memory are not thereby known to have the
    same memory. `True` would claim they match; `False` would call two runs from
    one machine incomparable. `unknown` is the only honest answer.
    """
    verdict = comparability(env(memory_gb=None), env(memory_gb=None))
    assert verdict["same_hardware"] is True, "nothing differs"
    assert verdict["verdict"] == "unknown"
    assert "memory_gb" in verdict["unknown_fields"]


def test_an_undetectable_gpu_probe_is_unknown_but_a_successful_empty_one_is_not() -> None:
    """After a successful probe, "no GPUs" is a finding, not an absence."""
    probed = comparability(
        env(gpus=[], gpu_detection="probed", inference=declared_backend({"backend": "x"})),
        env(gpus=[], gpu_detection="probed", inference=declared_backend({"backend": "x"})),
    )
    assert "gpu_names" not in probed["unknown_fields"]

    blind = comparability(
        env(gpus=[], gpu_detection="not_detectable"),
        env(gpus=[], gpu_detection="not_detectable"),
    )
    assert "gpu_names" in blind["unknown_fields"]


def test_the_profile_ignores_things_that_do_not_change_latency() -> None:
    # A renamed host must not make a machine incomparable with itself.
    profile = hardware_profile(env())
    assert set(profile) == set(PROFILE_FIELDS)
    assert "timestamp" not in profile
    assert "cpu" not in profile


def test_a_missing_hardware_block_does_not_crash() -> None:
    """Bundles written before this existed have no hardware block at all."""
    verdict = comparability({"os": "Linux", "machine": "x86_64"}, env())
    assert verdict["verdict"] in {"unknown", "not_comparable"}
    assert verdict["unknown_fields"]


# --- the latency split ------------------------------------------------------


def test_the_split_accounts_for_all_the_wall_time() -> None:
    split = latency_split({"wall_ms": 100.0, "model_ms": 70.0, "tool_ms": 20.0})
    assert split["harness_ms"] == 10.0
    assert split["model_share"] == 0.7
    assert split["tool_share"] == 0.2


def test_unreported_model_time_does_not_become_tool_time() -> None:
    """The tempting bug: attribute the remainder to whatever *was* measured."""
    split = latency_split({"wall_ms": 100.0, "model_ms": None, "tool_ms": 20.0})
    assert split["model_ms"] is None
    assert split["harness_ms"] is None, "a harness figure from an unmeasured model time is invented"
    assert split["tool_share"] == 0.2
    assert split["model_time_reported"] is False


def test_zero_model_time_is_distinguishable_from_unreported() -> None:
    reported = latency_split({"wall_ms": 100.0, "model_ms": 0.0, "tool_ms": 20.0})
    assert reported["model_time_reported"] is True
    assert reported["model_ms"] == 0.0


def test_a_split_never_goes_negative() -> None:
    # Clock skew or overlapping measurement can exceed the wall time; a negative
    # harness figure would be nonsense presented as data.
    split = latency_split({"wall_ms": 10.0, "model_ms": 8.0, "tool_ms": 8.0})
    assert split["harness_ms"] == 0.0


def test_no_wall_time_is_all_unknown() -> None:
    for bad in ({}, {"wall_ms": 0}, {"wall_ms": None}):
        assert latency_split(bad)["wall_ms"] is None


def test_the_aggregate_says_how_much_of_the_sample_answered() -> None:
    """A split over 2 of 200 runs does not describe those 200 runs."""
    rows = [{"wall_ms": 10.0, "model_ms": 5.0, "tool_ms": 4.0}] + [
        {"wall_ms": 10.0, "model_ms": None, "tool_ms": 4.0} for _ in range(9)
    ]
    got = aggregate_latency(rows)
    assert got["runs"] == 10
    assert got["runs_reporting_model_time"] == 1


def test_an_aggregate_over_nothing_is_unknown_not_zero() -> None:
    got = aggregate_latency([])
    assert got["runs"] == 0
    assert got["model_ms_mean"] is None


# --- it reaches the artifacts -----------------------------------------------


def test_a_written_bundle_records_the_hardware() -> None:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    environment = json.loads((bundles[0] / "environment.json").read_text(encoding="utf-8"))
    assert "hardware" in environment, "a latency number with no machine behind it"
    assert environment["hardware"]["gpu_detection"] in {"probed", "not_detectable"}


def test_committed_bundles_are_comparable_with_each_other() -> None:
    """They came off one machine, so anything else means the profile is unstable."""
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if len(bundles) < 2:
        pytest.skip("need two bundles")
    first, second = (
        json.loads((b / "environment.json").read_text(encoding="utf-8")) for b in bundles[:2]
    )
    assert comparability(first, second)["same_hardware"] is True


def test_the_benchmark_summary_carries_the_split() -> None:
    from tooltrace.analysis.stats import summarize_reliability

    summary = summarize_reliability(
        [
            {"success": True, "wall_ms": 100.0, "model_ms": 70.0, "tool_ms": 20.0},
            {"success": True, "wall_ms": 100.0, "model_ms": 60.0, "tool_ms": 30.0},
        ]
    )
    assert summary["latency"]["model_ms_mean"] == 65.0
    assert summary["latency"]["tool_ms_mean"] == 25.0
