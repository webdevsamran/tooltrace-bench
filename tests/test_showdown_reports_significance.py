"""Showdown must not claim a winner the sample cannot support.

`cmd_showdown` sorted on the success-rate point estimate and stopped. It put a
confidence interval in its own output and never consulted it, so two agents at
`--runs 1` came back in a definite order. Meanwhile the repository ships
`significance_note`, `paired_delta` and `effect_size_cohens_h` -- whose entire
purpose is to refuse that claim -- with no caller outside the test suite.
"""

from __future__ import annotations

import json

import pytest
from tooltrace.cli.main import _intervals_are_disjoint, main


def _showdown(capsys, *extra: str) -> dict:
    code = main(
        [
            "showdown",
            "--agents",
            "scripted,scripted",
            "--task",
            "file-editing/fix-config-typo",
            "--runs",
            "1",
            "--json",
            *extra,
        ]
    )
    assert code == 0
    return json.loads(capsys.readouterr().out)


def test_a_tiny_sample_is_reported_as_provisional(capsys) -> None:
    payload = _showdown(capsys)
    assert payload["ranking_is_provisional"] is True
    assert payload["verdict"] == "not distinguishable at this sample size"
    assert "below 30" in payload["note"]


def test_standings_still_carry_the_per_agent_numbers(capsys) -> None:
    payload = _showdown(capsys)
    rows = payload["standings"]
    assert len(rows) == 2
    for row in rows:
        assert row["agent"] == "scripted"
        assert row["success_rate"] == 1.0
        assert row["ci"] and len(row["ci"]) == 2
        assert "flakiness" in row  # previously computed and silently dropped


def test_challengers_are_compared_to_the_leader_pairwise(capsys) -> None:
    payload = _showdown(capsys)
    challenger = payload["standings"][1]
    assert challenger["paired_vs_leader"] == {
        "wins": 0.0,
        "losses": 0.0,
        "ties": 1.0,
        "discordant_rate": 0.0,
    }
    assert challenger["effect_size_h"] == 0.0


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([0.8, 1.0], [0.1, 0.4], True),
        ([0.1, 0.4], [0.8, 1.0], True),
        ([0.2, 1.0], [0.2, 1.0], False),
        ([0.2, 0.6], [0.5, 0.9], False),
        ([None, 1.0], [0.2, 0.4], False),
        ([0.2, 0.4], "not-an-interval", False),
    ],
)
def test_interval_separation_never_infers_separation_from_missing_data(a, b, expected) -> None:
    assert _intervals_are_disjoint(a, b) is expected


def test_a_separated_large_sample_is_ranked(monkeypatch, capsys) -> None:
    """The verdict must be reachable, or the guard is just an unconditional refusal."""
    import tooltrace.metrics.reliability as reliability

    monkeypatch.setattr(reliability, "significance_note", lambda *a, **k: "sample sizes sufficient")

    from tooltrace.cli.main import cmd_showdown

    calls = {"n": 0}
    import tooltrace.runners.benchmark as benchmark_mod

    real = benchmark_mod.run_benchmark

    def fake(tasks, agent, config=None, runs=1, out_dir=None):
        run = real(tasks, agent, config, runs=runs, out_dir=out_dir)
        # Separate the two agents' intervals so the disjointness test can pass.
        calls["n"] += 1
        low, high = (0.9, 1.0) if calls["n"] == 1 else (0.0, 0.1)
        run.summary["overall"]["ci_low"] = low
        run.summary["overall"]["ci_high"] = high
        run.summary["overall"]["rate"] = high
        return run

    monkeypatch.setattr(benchmark_mod, "run_benchmark", fake)

    import argparse

    args = argparse.Namespace(
        agents="scripted,scripted",
        task="file-editing/fix-config-typo",
        runs=1,
        agent_config=None,
        out=None,
        json=True,
    )
    assert cmd_showdown(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "ranked"
    assert payload["ranking_is_provisional"] is False
