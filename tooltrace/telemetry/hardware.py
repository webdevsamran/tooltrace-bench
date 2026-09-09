"""What machine a run happened on, and whether two runs can be compared at all.

`environment.json` recorded five fields: python version, platform string, OS,
machine and a timestamp. That is enough to know a run happened on Windows on
x86_64, and not enough to know whether its latency number means anything next to
another run's.

Latency is the axis where this bites. A p95 of 40 ms on a laptop and 40 ms on a
GPU server are the same number describing different things, and a leaderboard
that ranks them together is measuring the hardware while claiming to measure the
agent. So this module does two things:

1. **Detect what can honestly be detected** — CPU count, total memory, and GPUs
   via `nvidia-smi` if it happens to be there. No new dependency, and nothing is
   guessed: an unknown is `None`, never a plausible-looking default. The previous
   `WorkerInventory.gpu = False` is exactly the failure mode being avoided — a
   hardcoded `False` reads as "checked, and there is no GPU".

2. **Say when two runs are not comparable.** `hardware_profile` reduces a
   machine to the handful of things that change a latency number, and
   `comparability` reports what differs. It deliberately does *not* fold into
   `compatibility_key`: that key gates whether artifacts are *readable* together,
   which is a correctness question with one right answer. Hardware difference is
   a caveat on interpretation, and silently refusing to compare two runs from
   different laptops would make the tool useless for the case it is most used
   for.

Nothing here influences scoring. A run's score must not depend on the machine it
ran on, or reproduction would be impossible.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any

#: Fields that materially change a latency measurement. Kept small on purpose:
#: a profile that includes the hostname would make every machine incomparable
#: with itself after a rename.
PROFILE_FIELDS = ("os", "machine", "cpu_count", "memory_gb", "gpu_names", "backend")


def cpu_count() -> int | None:
    """Logical CPUs, or None. `os.cpu_count()` can genuinely return None."""
    return os.cpu_count()


def total_memory_gb() -> float | None:
    """Total RAM in GiB, or None when the platform will not say.

    `os.sysconf` covers Linux and macOS. On Windows there is no dependency-free
    way, so this returns None rather than a number derived from a guess — a
    fabricated memory size is worse than an absent one, because it looks
    measured.
    """
    # Reached through getattr because `os.sysconf` does not exist on Windows at
    # all -- not as a function that fails, as a missing attribute. A direct call
    # is also a type error there, since the platform's stubs omit it.
    sysconf = getattr(os, "sysconf", None)
    if sysconf is None:
        return None
    try:
        pages = sysconf("SC_PHYS_PAGES")
        page_size = sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return None
    if not isinstance(pages, int) or not isinstance(page_size, int) or pages <= 0:
        return None
    return round(pages * page_size / (1024**3), 2)


def detect_gpus(*, timeout: float = 4.0) -> list[dict[str, Any]]:
    """GPUs reported by `nvidia-smi`, or an empty list.

    An empty list means **nothing was detected**, which is not the same as
    "there is no GPU": a machine can have an AMD or Apple GPU and no
    `nvidia-smi`. `gpu_detection` below reports which of the two it is, because
    a benchmark that quietly conflates them would let a GPU run be compared
    against a CPU run.
    """
    if not shutil.which("nvidia-smi"):
        return []
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            timeout=timeout,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []

    gpus: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            continue
        try:
            vram = int(float(parts[1]))
        except ValueError:
            vram = 0
        gpus.append(
            {
                "name": parts[0],
                "vram_mb": vram or None,
                "driver_version": parts[2] if len(parts) > 2 else "",
            }
        )
    return gpus


def gpu_detection() -> str:
    """How to read an empty GPU list: `none_found` versus `not_detectable`."""
    if not shutil.which("nvidia-smi"):
        # No probe was possible. Reporting "no GPU" here is the bug this string
        # exists to prevent.
        return "not_detectable"
    return "probed"


def declared_backend(agent_config: dict[str, Any] | None) -> dict[str, Any]:
    """The inference backend, as *declared* by the caller.

    None of this is detectable from inside the harness: a model served over an
    OpenAI-compatible endpoint could be anything, quantized any way, on any
    hardware. So it is recorded as a declaration and labelled as one. A field
    named `backend` that silently held a guess would be worse than an empty one,
    because a reader would compare across it.
    """
    config = agent_config or {}
    declared = {
        "backend": str(config.get("backend") or ""),
        "engine_version": str(config.get("engine_version") or ""),
        "model": str(config.get("model") or ""),
        "quantization": str(config.get("quantization") or ""),
        "base_url": str(config.get("base_url") or ""),
    }
    return {
        **declared,
        # An explicit flag rather than an inference from emptiness: a caller who
        # declared nothing and a caller who declared "" are the same case, and
        # both must read as "not stated".
        "is_declared": any(declared.values()),
        "source": "declared_by_caller",
    }


def hardware_metadata(agent_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """The block that goes into `environment.json`, beside the existing fields."""
    gpus = detect_gpus()
    return {
        "cpu_count": cpu_count(),
        "cpu": platform.processor() or "",
        "memory_gb": total_memory_gb(),
        "gpus": gpus,
        "gpu_detection": gpu_detection(),
        "inference": declared_backend(agent_config),
    }


def hardware_profile(environment: dict[str, Any]) -> dict[str, Any]:
    """Reduce an environment record to what changes a latency number."""
    hardware = environment.get("hardware")
    hardware = hardware if isinstance(hardware, dict) else {}
    gpus = hardware.get("gpus")
    gpus = gpus if isinstance(gpus, list) else []
    inference = hardware.get("inference")
    inference = inference if isinstance(inference, dict) else {}
    return {
        "os": str(environment.get("os") or ""),
        "machine": str(environment.get("machine") or ""),
        "cpu_count": hardware.get("cpu_count"),
        "memory_gb": hardware.get("memory_gb"),
        "gpu_names": sorted(str(g.get("name", "")) for g in gpus if isinstance(g, dict)),
        "backend": str(inference.get("backend") or ""),
    }


def _unknown_fields(profile: dict[str, Any], probed: bool) -> set[str]:
    """Fields this record could not determine.

    An empty GPU list is only unknown when no probe was possible: after a
    successful `nvidia-smi` call, "no GPUs" is a finding. Conflating the two is
    the mistake the old hardcoded `gpu = False` made.
    """
    unknown = set()
    for field in PROFILE_FIELDS:
        value = profile.get(field)
        if field == "gpu_names":
            if not value and not probed:
                unknown.add(field)
        elif value in (None, ""):
            unknown.add(field)
    return unknown


def comparability(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Whether two runs' latency numbers describe the same conditions.

    The verdict is three-state, not a boolean, and that is the substance of this
    function. A boolean has to lie in one direction: `True` would claim two runs
    match when the record simply never determined their memory size, and `False`
    would call two runs from one machine incomparable because neither declared a
    backend. Neither is what a reader needs.

    - `comparable`     — everything relevant was determined and agrees.
    - `not_comparable` — something relevant was determined and differs.
    - `unknown`        — nothing differs, but something was never determined,
                         so agreement cannot be established.

    Differences are returned as both values rather than a flag: "not comparable"
    is not actionable, and "8 CPUs versus 64" is.
    """
    left, right = hardware_profile(a), hardware_profile(b)
    differences = {
        field: [left.get(field), right.get(field)]
        for field in PROFILE_FIELDS
        if left.get(field) != right.get(field)
    }
    unknown = sorted(_unknown_fields(left, _probed(a)) | _unknown_fields(right, _probed(b)))
    verdict = "not_comparable" if differences else "unknown" if unknown else "comparable"
    return {
        "verdict": verdict,
        # Nothing *detected* differs. On its own this is not permission to
        # compare; `verdict` is.
        "same_hardware": not differences,
        "differences": differences,
        "unknown_fields": unknown,
    }


def _probed(environment: dict[str, Any]) -> bool:
    hardware = environment.get("hardware")
    hardware = hardware if isinstance(hardware, dict) else {}
    return hardware.get("gpu_detection") == "probed"


def latency_split(result: dict[str, Any]) -> dict[str, Any]:
    """Where a run's wall time went: inference, tools, or the harness.

    `model_ms` and `tool_ms` already existed on every result and nothing ever
    reported them together, so nobody could see whether a slow agent was slow at
    thinking or slow at doing. That is the first question anyone optimising an
    agent has.

    `model_ms` is None whenever the adapter cannot report it — the scripted agent
    has no model at all — and in that case the split stays None rather than
    attributing the whole wall time to tools. A harness overhead figure derived
    from an unmeasured model time would be pure invention.
    """
    wall = result.get("wall_ms")
    model = result.get("model_ms")
    tool = result.get("tool_ms")
    if not isinstance(wall, int | float) or wall <= 0:
        return {
            "wall_ms": None,
            "model_ms": None,
            "tool_ms": None,
            "harness_ms": None,
            "model_share": None,
            "tool_share": None,
            "model_time_reported": isinstance(model, int | float),
        }

    tool_ms = float(tool) if isinstance(tool, int | float) else None
    model_ms = float(model) if isinstance(model, int | float) else None
    harness_ms = (
        round(max(0.0, wall - model_ms - tool_ms), 3)
        if model_ms is not None and tool_ms is not None
        else None
    )
    return {
        "wall_ms": round(float(wall), 3),
        "model_ms": round(model_ms, 3) if model_ms is not None else None,
        "tool_ms": round(tool_ms, 3) if tool_ms is not None else None,
        "harness_ms": harness_ms,
        "model_share": round(model_ms / wall, 6) if model_ms is not None else None,
        "tool_share": round(tool_ms / wall, 6) if tool_ms is not None else None,
        # Named so a reader can tell "the model took 0 ms" from "nobody told us".
        "model_time_reported": model_ms is not None,
    }


def aggregate_latency(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean split across runs, preserving unknowns as unknown."""
    splits = [latency_split(r) for r in results]
    measured = [s for s in splits if s["wall_ms"] is not None]
    if not measured:
        return {"runs": 0, "model_ms_mean": None, "tool_ms_mean": None, "harness_ms_mean": None}

    def mean(key: str) -> float | None:
        values = [s[key] for s in measured if s[key] is not None]
        return round(sum(values) / len(values), 3) if values else None

    with_model = [s for s in measured if s["model_time_reported"]]
    return {
        "runs": len(measured),
        "wall_ms_mean": mean("wall_ms"),
        "model_ms_mean": mean("model_ms"),
        "tool_ms_mean": mean("tool_ms"),
        "harness_ms_mean": mean("harness_ms"),
        "model_share_mean": mean("model_share"),
        "tool_share_mean": mean("tool_share"),
        # How much of the sample could answer the question at all. A split over
        # 2 of 200 runs is not a description of those 200 runs.
        "runs_reporting_model_time": len(with_model),
    }
