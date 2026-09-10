"""What a run cost in tokens, cache hits and energy -- where any of that is real.

`hardware.py` records the machine and splits model time from tool time.
This is the next layer down: the four questions a team asks once they are
running a local model and paying for the GPU themselves.

Each answer here is either measured from something the provider actually
reported, or absent. There is no estimate anywhere in this file, and that is a
deliberate constraint rather than an omission -- a plausible-looking number for
energy or TTFT would be indistinguishable from a measured one three functions
later, and the whole value of this project is that its numbers can be traced to
where they came from.

## What each one can and cannot see

**Prefill overhead** is fully measurable and nobody measures it. Every request
carries the system prompt and the tool catalogue before the task even starts,
and that is charged on every turn of every run. It is computed from the
catalogue this project generates, so it is exact rather than sampled.

**Cache hit rate** comes from `cached_prompt_tokens`, which providers report and
which nothing here read until recently. A run with no cached count is `None`,
not zero: a provider that says nothing about caching is not one that cached
nothing, and those two bill identically while meaning different things.

**TTFT** cannot be measured without streaming, and none of the HTTP adapters
here stream. Reported as unmeasured with the reason, rather than approximated
from total latency -- which would be a measurement of the response length.

**Energy** is read from the platform where the platform exposes it: Linux RAPL
counters, or `nvidia-smi` for a GPU. On a machine with neither it is unmeasured.
Multiplying a TDP by a duration would produce a carbon figure with a decimal
point and no relationship to what the machine drew.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path
from typing import Any

#: Where Linux exposes running energy counters, in microjoules.
RAPL_ROOT = Path("/sys/class/powercap")

#: Rough grams of CO2 per kWh. Deliberately *not* used to produce a number:
#: carbon intensity varies by grid, by hour and by contract, and a single
#: constant would turn a measured energy figure into an invented carbon one.
#: Recorded so a caller who knows their own intensity can multiply.
CARBON_NOTE = (
    "Carbon depends on grid intensity where and when the run happened, which "
    "varies by hour. This reports energy; multiply by your own intensity figure "
    "rather than accepting one from a benchmark."
)


# ---------------------------------------------------------------------------
# Prefill: what every request pays before the task starts
# ---------------------------------------------------------------------------


def _approx_tokens(text: str) -> int:
    """A deliberately crude token estimate, and labelled as one everywhere.

    No tokeniser ships with this package and adding one for a diagnostic would
    be a poor trade. Four characters per token is the usual rule of thumb; it is
    wrong by 10-20% and the field name says `approx` so nobody reads it as a
    billing figure.
    """
    return max(1, round(len(text) / 4))


def prefill_overhead(allowed_tools: list[str] | None = None) -> dict[str, Any]:
    """What the system prompt and tool catalogue cost before any work happens.

    Measurable exactly, charged on every turn of every run, and almost never
    looked at. A catalogue that grew by 400 tokens costs that on each of ten
    steps across each of a hundred runs, and no other metric in this project
    would move.
    """
    from tooltrace.agents.chat_base import SYSTEM_PROMPT
    from tooltrace.agents.tool_schemas import render_prompt_block

    catalogue = render_prompt_block(allowed_tools)
    #: The template minus its substitution slots, which is the fixed part.
    scaffold = SYSTEM_PROMPT.replace("{tools}", "").replace("{objective}", "")
    scaffold = scaffold.replace("{description}", "").replace("{files}", "")

    catalogue_chars = len(catalogue)
    scaffold_chars = len(scaffold)
    return {
        "tools": len([line for line in catalogue.splitlines() if line.startswith("- ")]),
        "catalogue_chars": catalogue_chars,
        "scaffold_chars": scaffold_chars,
        "total_chars": catalogue_chars + scaffold_chars,
        "approx_tokens": _approx_tokens(catalogue) + _approx_tokens(scaffold),
        "approx_catalogue_tokens": _approx_tokens(catalogue),
        "is_estimate": True,
        "statement": (
            f"~{_approx_tokens(catalogue) + _approx_tokens(scaffold)} tokens are sent before "
            "the task begins, on every turn of every run. Roughly four characters per token: "
            "no tokeniser ships here, so this is a diagnostic rather than a billing figure."
        ),
    }


# ---------------------------------------------------------------------------
# Cache: what the provider says it reused
# ---------------------------------------------------------------------------


def cache_profile(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Prompt-cache hit rate across runs, from what providers reported.

    A run whose provider said nothing about caching is excluded rather than
    counted as a miss. "We do not know" and "nothing was cached" bill
    identically and mean entirely different things, and averaging the first into
    the second would make every local model look like it had no cache.
    """
    reported: list[tuple[float, float]] = []
    silent = 0
    for result in results:
        usage = (result.get("usage") or {}).get("tokens") or {}
        prompt = usage.get("prompt_tokens")
        cached = usage.get("cached_prompt_tokens")
        if not isinstance(prompt, int | float) or not isinstance(cached, int | float):
            silent += 1
            continue
        if prompt <= 0:
            silent += 1
            continue
        reported.append((float(cached), float(prompt)))

    if not reported:
        return {
            "measurable": False,
            "runs": len(results),
            "runs_reporting_cache": 0,
            "reason": (
                f"none of {len(results)} run(s) reported a cached-prompt count. Most local "
                "servers report none, and OpenAI reports it only above a minimum prompt size"
            ),
            "carbon_note": None,
        }

    cached_total = sum(c for c, _ in reported)
    prompt_total = sum(p for _, p in reported)
    return {
        "measurable": True,
        "runs": len(results),
        "runs_reporting_cache": len(reported),
        "runs_silent_about_cache": silent,
        "cached_tokens": round(cached_total),
        "prompt_tokens": round(prompt_total),
        "hit_rate": round(cached_total / prompt_total, 6) if prompt_total else None,
        "statement": (
            f"{cached_total / prompt_total:.1%} of prompt tokens were served from cache across "
            f"{len(reported)} run(s) that reported it"
            + (
                f"; {silent} run(s) said nothing about caching and are excluded rather than "
                "counted as misses"
                if silent
                else ""
            )
            + "."
        ),
    }


# ---------------------------------------------------------------------------
# TTFT: why it is not here
# ---------------------------------------------------------------------------


def time_to_first_token(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Unmeasured, with the reason, because approximating it would be worse.

    TTFT is the interval between the request and the first token back, and it
    needs a streaming response to observe. None of the HTTP adapters here
    stream: they post a request and read a complete body.

    Dividing total latency by anything would produce a number that moves with
    the *length* of the response, which is the opposite of what TTFT measures --
    a fast model writing a long answer would look slow to start.
    """
    return {
        "measurable": False,
        "runs": len(results),
        "reason": (
            "no adapter here streams, so there is no first token to time. `model_ms` is "
            "request-to-complete-response and includes generation of the whole reply"
        ),
        "what_would_be_needed": (
            "an adapter that sets `stream: true` and timestamps the first chunk. The "
            "`streaming` adapter drives a child process per step, which is a different "
            "kind of streaming and does not expose token timing either"
        ),
        "not_approximated_because": (
            "any division of total latency would move with the length of the response, "
            "so a fast model writing a long answer would read as slow to start"
        ),
    }


# ---------------------------------------------------------------------------
# Energy, where the platform exposes it
# ---------------------------------------------------------------------------


def _rapl_microjoules() -> dict[str, int]:
    """Per-domain energy counters from Linux RAPL, or {} anywhere else."""
    readings: dict[str, int] = {}
    if not RAPL_ROOT.is_dir():
        return readings
    for domain in sorted(RAPL_ROOT.glob("intel-rapl:*")):
        name_file = domain / "name"
        energy_file = domain / "energy_uj"
        if not (name_file.is_file() and energy_file.is_file()):
            continue
        with contextlib.suppress(OSError, ValueError):
            readings[name_file.read_text().strip()] = int(energy_file.read_text().strip())
    return readings


def _gpu_power_watts(*, timeout: float = 4.0) -> list[float]:
    """Instantaneous GPU draw via `nvidia-smi`, or [] when it is not there."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    watts: list[float] = []
    for line in proc.stdout.splitlines():
        with contextlib.suppress(ValueError):
            watts.append(float(line.strip()))
    return watts


def energy_sources() -> dict[str, Any]:
    """Which energy counters this machine actually exposes.

    Probed rather than assumed, and reported before any measurement is
    attempted: a report saying "0 joules" on a machine with no counters would be
    a measurement of nothing presented as a measurement of something.
    """
    rapl = _rapl_microjoules()
    gpu = _gpu_power_watts()
    available = bool(rapl) or bool(gpu)
    return {
        "available": available,
        "cpu_rapl_domains": sorted(rapl),
        "gpu_power_readings": len(gpu),
        "platform": os.name,
        "statement": (
            (
                f"energy is readable here: {len(rapl)} RAPL domain(s), "
                f"{len(gpu)} GPU power reading(s)"
            )
            if available
            else (
                "no energy counter is exposed on this machine. Linux exposes RAPL under "
                "/sys/class/powercap and NVIDIA GPUs answer nvidia-smi; with neither, energy "
                "is unmeasured. It is not estimated from a TDP: that would be arithmetic "
                "about a datasheet, not a measurement of this run"
            )
        ),
        "carbon_note": CARBON_NOTE,
    }


class EnergyWindow:
    """Energy drawn between two instants, where the platform will say.

    A context manager rather than a single reading, because RAPL counters are
    cumulative: the useful quantity is a difference, and a caller that recorded
    an absolute value would be recording how long the machine had been on.
    """

    def __init__(self) -> None:
        self.start: dict[str, int] = {}
        self.end: dict[str, int] = {}

    def __enter__(self) -> EnergyWindow:
        self.start = _rapl_microjoules()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.end = _rapl_microjoules()

    def joules(self) -> dict[str, Any]:
        if not self.start or not self.end:
            return {"measurable": False, "reason": "no RAPL counters on this machine"}
        deltas: dict[str, float] = {}
        for domain, started in self.start.items():
            finished = self.end.get(domain)
            if finished is None or finished < started:
                # A counter that went backwards wrapped. Reported as unknown for
                # that domain rather than as a huge negative or a guessed wrap
                # point, which would be a fabricated number.
                continue
            deltas[domain] = (finished - started) / 1_000_000
        return {
            "measurable": bool(deltas),
            "joules_by_domain": {k: round(v, 3) for k, v in deltas.items()},
            "total_joules": round(sum(deltas.values()), 3) if deltas else None,
            "carbon_note": CARBON_NOTE,
        }


# ---------------------------------------------------------------------------
# The handler matrix: what has actually been run here
# ---------------------------------------------------------------------------


def handler_matrix(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Which (agent, model, backend) combinations have actually been measured.

    Generated from recorded runs and never from a list of what is supported. A
    hardcoded support matrix says what somebody believed when they typed it; a
    matrix built from bundles says what has been run, which is the only claim
    worth publishing.

    The consequence is that this table is usually mostly empty, and it should
    be: nobody has run every model on every backend.
    """
    combinations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for result in results:
        config = result.get("agent_config") or {}
        agent = str(result.get("agent") or "unknown")
        model = str(config.get("model") or "(not declared)")
        backend = str(config.get("backend") or config.get("base_url") or "(not declared)")
        key = (agent, model, backend)
        entry = combinations.setdefault(
            key, {"agent": agent, "model": model, "backend": backend, "runs": 0, "successes": 0}
        )
        entry["runs"] += 1
        if result.get("success"):
            entry["successes"] += 1

    rows = sorted(combinations.values(), key=lambda r: (r["agent"], r["model"], r["backend"]))
    for row in rows:
        row["success_rate"] = round(row["successes"] / row["runs"], 6) if row["runs"] else None
        # Below ten runs a rate is a wide interval, and a matrix cell showing
        # "100%" from one run is the most misleading thing this table could do.
        row["sample_is_small"] = row["runs"] < 10

    undeclared = [r for r in rows if r["model"] == "(not declared)"]
    return {
        "combinations": rows,
        "counts": {
            "combinations": len(rows),
            "runs": len(results),
            "small_samples": sum(1 for r in rows if r["sample_is_small"]),
        },
        "statement": (
            f"{len(rows)} (agent, model, backend) combination(s) across {len(results)} run(s). "
            "Built from what ran, not from a list of what is supported: a hardcoded matrix "
            "records what somebody believed when they typed it."
            + (
                f" {len(undeclared)} combination(s) declare no model, so they group together "
                "under one row that is not really one configuration."
                if undeclared
                else ""
            )
        ),
    }


def report(results: list[dict[str, Any]], allowed_tools: list[str] | None = None) -> dict[str, Any]:
    """Everything above, for one set of runs."""
    return {
        "prefill": prefill_overhead(allowed_tools),
        "cache": cache_profile(results),
        "ttft": time_to_first_token(results),
        "energy": energy_sources(),
        "handlers": handler_matrix(results),
        "quantization": quantization_curve(results),
    }


def quantization_curve(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Quality against speed, by declared quantization.

    The question a team asks once the GPU is theirs: is Q4 good enough, or is
    the accuracy it costs worse than the memory it saves?

    The arithmetic is trivial and the **validity condition is not**, so it is
    checked rather than assumed. A comparison across quantizations means
    something only when everything else was held fixed -- same model, same
    backend, same machine. Two quantizations benchmarked on different hardware
    produce a latency curve that is mostly a curve of the two machines, and
    reporting it as a quantization effect would be the most confidently wrong
    number in this module.

    So each group carries what varied alongside it, and the report refuses to
    call itself a curve when more than the quantization moved.
    """
    groups: dict[str, dict[str, Any]] = {}
    unlabelled = 0

    for result in results:
        config = result.get("agent_config") or {}
        level = str(config.get("quantization") or "").strip()
        if not level:
            # Not grouped under "unknown": that would be a bucket mixing every
            # unlabelled run into one row and calling it a quantization.
            unlabelled += 1
            continue
        entry = groups.setdefault(
            level,
            {
                "quantization": level,
                "runs": 0,
                "successes": 0,
                "wall_ms_total": 0.0,
                "wall_ms_runs": 0,
                "models": set(),
                "backends": set(),
                "machines": set(),
            },
        )
        entry["runs"] += 1
        entry["successes"] += 1 if result.get("success") else 0
        wall = result.get("wall_ms")
        if isinstance(wall, int | float):
            entry["wall_ms_total"] += float(wall)
            entry["wall_ms_runs"] += 1
        entry["models"].add(str(config.get("model") or "(not declared)"))
        entry["backends"].add(str(config.get("backend") or "(not declared)"))
        environment = result.get("environment") or {}
        entry["machines"].add(str((environment or {}).get("machine") or "(not recorded)"))

    points = []
    for entry in sorted(groups.values(), key=lambda e: e["quantization"]):
        points.append(
            {
                "quantization": entry["quantization"],
                "runs": entry["runs"],
                "success_rate": round(entry["successes"] / entry["runs"], 6),
                "wall_ms_mean": (
                    round(entry["wall_ms_total"] / entry["wall_ms_runs"], 3)
                    if entry["wall_ms_runs"]
                    else None
                ),
                "models": sorted(entry["models"]),
                "backends": sorted(entry["backends"]),
                "sample_is_small": entry["runs"] < 10,
            }
        )

    models = {m for entry in groups.values() for m in entry["models"]}
    backends = {b for entry in groups.values() for b in entry["backends"]}
    machines = {m for entry in groups.values() for m in entry["machines"]}
    confounded = [
        label
        for label, values in (("model", models), ("backend", backends), ("machine", machines))
        if len(values) > 1
    ]

    if len(points) < 2:
        return {
            "comparable": False,
            "points": points,
            "unlabelled_runs": unlabelled,
            "reason": (
                f"{len(points)} quantization level(s) recorded"
                + (
                    f"; {unlabelled} run(s) declared none, so they are excluded rather than "
                    "grouped into an invented 'unknown' level"
                    if unlabelled
                    else ""
                )
                + ". A curve needs at least two points measured the same way."
            ),
        }

    return {
        # Not "did it work" -- whether the difference between the points can be
        # attributed to the quantization at all.
        "comparable": not confounded,
        "points": points,
        "unlabelled_runs": unlabelled,
        "confounded_by": confounded,
        "statement": (
            f"{len(points)} quantization level(s) across {sum(p['runs'] for p in points)} run(s)"
            + (
                ". Everything else was held fixed, so the difference between these points is "
                "attributable to the quantization."
                if not confounded
                else f". **{', '.join(confounded)} also varied**, so this is not a "
                "quantization curve: the difference between the points is the sum of every "
                "axis that moved, and nothing here separates them."
            )
        ),
    }
