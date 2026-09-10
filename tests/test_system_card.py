"""A system card that cannot flatter, and a self-audit that cannot be scored.

A hand-written system card becomes marketing: the capabilities section fills up,
the limitations section reads "may occasionally make mistakes", and the
"unmeasured" section does not exist at all. Generated from runs, the incentives
invert — and the section a benchmark can fill best is precisely the one a human
author leaves out, because *what was never measured* is what a benchmark knows.

Most of these tests are about refusing to overclaim. A 3-run 100% is not a
capability and a 3-run 0% is not a limitation; both belong in a third section
that exists so neither neighbour absorbs them.

The self-audit deliberately produces **no percentage**. "Evidence completeness:
73%" is a number that ends up on a slide, and there is no weighting of these
checks that would mean anything to a regulator. A test asserts the score never
appears.
"""

from __future__ import annotations

import json

import pytest
from tooltrace.analysis.system_card import (
    MIN_RUNS_FOR_A_CLAIM,
    audit_evidence,
    build_card,
    render_card,
)
from tooltrace.cli.main import main

WHEN = "2026-09-09T00:00:00+00:00"


def runs(
    task: str, n: int, successes: int, *, agent: str = "a", cost: float | None = None
) -> list[dict]:
    return [
        {
            "agent": agent,
            "task_id": task,
            "success": i < successes,
            "failure_reason": "none" if i < successes else "execution",
            "usage": {"provider_cost_reported": cost, "model_time_ms": None},
        }
        for i in range(n)
    ]


def card(rows: list[dict], **over):
    kwargs = {"agent": "a", "generated_at": WHEN}
    kwargs.update(over)
    return build_card(rows, **kwargs)


# --- it refuses to overclaim ------------------------------------------------


def test_a_three_run_perfect_score_is_not_a_capability() -> None:
    got = card(runs("t/easy", 3, 3))
    assert got["capabilities"] == []
    assert got["insufficiently_measured"][0]["task"] == "t/easy"


def test_a_three_run_total_failure_is_not_a_limitation() -> None:
    got = card(runs("t/hard", 3, 0))
    assert got["limitations"] == []
    assert got["insufficiently_measured"][0]["task"] == "t/hard"


def test_enough_runs_do_produce_a_claim() -> None:
    got = card(runs("t/easy", MIN_RUNS_FOR_A_CLAIM, MIN_RUNS_FOR_A_CLAIM))
    assert got["capabilities"][0]["task"] == "t/easy"
    assert got["capabilities"][0]["runs"] == MIN_RUNS_FOR_A_CLAIM


def test_the_middle_ground_is_its_own_section() -> None:
    """Collapsing it into either neighbour is how a card starts overclaiming."""
    got = card(runs("t/flaky", 20, 14))
    assert got["capabilities"] == []
    assert got["limitations"] == []
    entry = got["insufficiently_measured"][0]
    assert "neither a capability nor a limitation" in entry["note"]


def test_every_claim_states_its_sample_size() -> None:
    got = card([*runs("t/a", 20, 20), *runs("t/b", 20, 2)])
    for entry in got["capabilities"] + got["limitations"]:
        assert entry["runs"] >= MIN_RUNS_FOR_A_CLAIM


def test_it_covers_only_the_agent_asked_for() -> None:
    rows = [*runs("t/a", 20, 20, agent="a"), *runs("t/a", 20, 0, agent="b")]
    assert card(rows, agent="a")["capabilities"]
    assert card(rows, agent="b")["limitations"]


# --- the section a hand-written card never has ------------------------------


def test_unmeasured_cost_is_named() -> None:
    got = card(runs("t/a", 20, 20))
    assert any("No run reported provider spend" in item for item in got["not_measured"])


def test_a_priced_run_removes_that_line() -> None:
    got = card(runs("t/a", 20, 20, cost=0.01))
    assert not any("provider spend" in item for item in got["not_measured"])


def test_absent_adversarial_evidence_is_named() -> None:
    got = card(runs("t/a", 20, 20), security={"attempts": 0})
    assert any("No security task was run" in item for item in got["not_measured"])


def test_a_small_adversarial_sample_is_called_out_rather_than_counted() -> None:
    got = card(runs("t/a", 20, 20), security={"attempts": 8})
    assert any("far too few" in item for item in got["not_measured"])


def test_uncovered_owasp_categories_are_listed_individually() -> None:
    coverage = {
        "total": 10,
        "covered": 1,
        "categories": [
            {"id": "AAI01", "label": "Prompt injection", "status": "covered"},
            {"id": "AAI06", "label": "Memory poisoning", "status": "not_covered"},
        ],
    }
    got = card(runs("t/a", 20, 20), coverage=coverage)
    listed = next(i for i in got["not_measured"] if "OWASP" in i)
    assert "AAI06" in listed
    assert "AAI01" not in listed


def test_the_catch_all_limit_is_always_present() -> None:
    """A benchmark says nothing about the failure modes it does not encode."""
    got = card(runs("t/a", 20, 20), security={"attempts": 100}, coverage=None)
    assert any("task packs do not cover" in item for item in got["not_measured"])


def test_the_card_never_describes_the_agent_in_general() -> None:
    got = card(runs("t/a", 20, 20))
    assert "not a description of the agent in general" in got["statement"]


# --- rendering --------------------------------------------------------------


def test_the_limits_are_not_an_appendix() -> None:
    """ "Not measured" is a section, not a footnote."""
    rendered = render_card(card(runs("t/a", 20, 20)))
    assert "## Not measured at all" in rendered


def test_an_empty_capabilities_section_says_so_rather_than_vanishing() -> None:
    rendered = render_card(card(runs("t/a", 3, 3)))
    assert "Nothing has enough runs behind it" in rendered


def test_the_card_is_ascii_only() -> None:
    """A Windows console mangles anything else, and a corrupted card undermines itself."""
    render_card(card([*runs("t/a", 20, 20), *runs("t/b", 20, 0)])).encode("ascii")


# --- the self-audit ---------------------------------------------------------


def bundles(n: int, *, verified: bool = True) -> list[dict]:
    return [{"bundle": f"b{i}", "verified": verified} for i in range(n)]


def test_it_produces_no_score() -> None:
    """The whole design decision. A percentage would be quoted as though it meant something."""
    got = audit_evidence(bundles=bundles(50))
    assert "%" not in got["statement"]
    assert "score" not in got
    assert "This is a checklist, not a score" in got["statement"]


def test_an_unverified_bundle_fails_that_check() -> None:
    got = audit_evidence(bundles=bundles(5, verified=False))
    check = next(c for c in got["checks"] if c["check"] == "every_bundle_verifies")
    assert check["passed"] is False
    assert "is not evidence; it is a file" in check["gap"]


def test_a_small_sample_is_a_gap_with_a_pointer() -> None:
    got = audit_evidence(bundles=bundles(5))
    check = next(c for c in got["checks"] if c["check"] == "sample_is_large_enough_to_quote")
    assert check["passed"] is False
    assert "tooltrace power" in check["gap"]


def test_self_reproduction_does_not_satisfy_the_reproduction_check() -> None:
    """Attested-by-you and reproduced-by-someone-else are different checks."""
    got = audit_evidence(bundles=bundles(50), attested=10, independently_attested=0)
    assert next(c for c in got["checks"] if c["check"] == "attested_at_all")["passed"] is True
    check = next(c for c in got["checks"] if c["check"] == "reproduced_by_someone_else")
    assert check["passed"] is False
    assert "a property you believe you have" in check["gap"]


def test_a_fully_evidenced_set_passes_everything() -> None:
    got = audit_evidence(
        bundles=bundles(50),
        attested=5,
        independently_attested=3,
        security_attempts=40,
        coverage={"covered": 7, "total": 10},
    )
    assert got["gaps"] == []
    assert got["passed"] == got["total"]


def test_no_evidence_at_all_says_so_first() -> None:
    got = audit_evidence(bundles=[])
    assert got["checks"][0]["passed"] is False
    assert "no evidence at all" in got["checks"][0]["gap"]


def test_every_failed_check_carries_a_gap_and_every_passing_one_does_not() -> None:
    got = audit_evidence(bundles=bundles(5))
    for check in got["checks"]:
        assert bool(check["gap"]) is not check["passed"]


# --- the CLI ----------------------------------------------------------------


def test_the_card_command_runs_against_this_repository(capsys) -> None:
    assert main(["card", "--bundles", "results", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent"] == "scripted"
    # Two runs per task in the shipped dataset, so nothing is claimable -- and
    # the card is honest about that rather than reporting a perfect record.
    assert payload["capabilities"] == []
    assert payload["not_measured"]


def test_the_card_command_writes_markdown(tmp_path, capsys) -> None:
    out = tmp_path / "card.md"
    assert main(["card", "--bundles", "results", "--out", str(out), "--json"]) == 0
    assert "## Not measured at all" in out.read_text(encoding="utf-8")


def test_the_self_audit_reports_this_repositorys_own_gaps(capsys) -> None:
    """It must be willing to fail on its author's evidence, or it means nothing."""
    assert main(["self-audit", "--bundles", "results", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gaps"], "an audit that passes its own author's evidence is not an audit"
    assert any("Nobody but you has reproduced" in gap for gap in payload["gaps"])


def test_the_self_audit_does_not_fail_the_build(capsys) -> None:
    """A gap is a finding. Exiting non-zero would make it a gate nobody passes."""
    assert main(["self-audit", "--bundles", "results"]) == 0


def test_both_commands_need_bundles(tmp_path, capsys) -> None:
    assert main(["card", "--bundles", str(tmp_path)]) != 0
    assert main(["self-audit", "--bundles", str(tmp_path)]) != 0


def test_the_card_asks_which_agent_when_there_are_several(tmp_path, capsys) -> None:
    import shutil
    from pathlib import Path

    results = Path("results")
    sources = sorted(results.glob("*.tooltrace"))
    if not sources:
        pytest.skip("no committed bundles")
    target = tmp_path / "mixed"
    target.mkdir()
    shutil.copytree(sources[0], target / sources[0].name)

    second = target / "other.tooltrace"
    shutil.copytree(sources[0], second)
    data = json.loads((second / "result.json").read_text(encoding="utf-8"))
    data["agent"] = "another"
    (second / "result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    assert main(["card", "--bundles", str(target)]) != 0
    assert "pick one with --agent" in capsys.readouterr().err
