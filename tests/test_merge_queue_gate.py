"""The merge-queue gate, and the four decisions that keep it switched on.

`pr-reliability.yml` compares a pull request against its own merge base. That is
the right question for review and the wrong one at merge time: a queue batches
several approved changes and merges the *combination*, and two changes that are
each harmless can be a regression together. Nothing checked that combination
until it was already on the default branch.

A merge-queue gate has one failure mode that matters more than any bug in it:
being turned off. So the properties tested here are the ones that decide whether
it survives its first week -- it blocks only on established regressions, it does
not gate on wall-clock, and it sweeps both sides on the same runner rather than
comparing against a baseline recorded on another machine on another day.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "merge-queue.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.is_file(), "the merge-queue workflow is missing"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def steps(workflow: dict) -> list[dict]:
    return workflow["jobs"]["gate"]["steps"]


def declared_metrics(text: str) -> list[str]:
    """The metric list on the command line, not the one in the prose above it.

    Splitting on the bare flag name picks up the comment that explains why
    `wall_ms` is excluded -- and then finds `wall_ms` in it.
    """
    return text.split("--metrics ")[1].split()[0].split(",")


# --- it runs on the thing nothing else checks -------------------------------


def test_it_triggers_on_the_merge_group(workflow: dict) -> None:
    """The batch, not the branch. `pull_request` is already covered."""
    trigger = workflow.get(True) if True in workflow else workflow.get("on")
    assert "merge_group" in trigger


def test_it_does_not_also_run_on_pull_request(workflow: dict) -> None:
    """That would double every PR's CI cost to re-ask a question already asked."""
    trigger = workflow.get(True) if True in workflow else workflow.get("on")
    assert "pull_request" not in trigger


def test_a_batch_is_not_cancelled_by_the_next_one(workflow: dict) -> None:
    """Two batches are two different combinations.

    Cancelling one because another arrived would leave that combination
    ungated, which is precisely the case this workflow exists for.
    """
    assert workflow["concurrency"]["cancel-in-progress"] is False


# --- the four decisions that keep it switched on ----------------------------


def test_both_sides_are_swept_in_the_same_job(workflow: dict) -> None:
    """A baseline recorded on another runner carries that machine's latency.

    A queue gate that blocks on a difference in hardware blocks at random.
    """
    names = [str(step.get("name", "")) for step in steps(workflow)]
    assert any("queued batch" in name for name in names)
    assert any("default branch" in name for name in names)


def test_it_does_not_gate_on_wall_clock(text: str) -> None:
    """A shared runner's latency is a fact about the runner.

    Blocking a merge on a noisy neighbour is exactly how this gate gets removed.
    """
    assert "wall_ms" not in declared_metrics(text)


def test_it_gates_on_token_count(text: str) -> None:
    """A change that leaves every score identical and doubles the spend is a
    regression no other metric here would notice."""
    assert "tokens_per_run" in text


def test_only_an_established_regression_blocks(text: str) -> None:
    """Exit 8 is `pr-report`'s established-regression code.

    Failing on an inconclusive result would make the gate a function of how many
    runs the repository can afford, and a queue that stalls on absent evidence
    is a queue somebody turns off.
    """
    assert 'code" = "8"' in text
    assert "inconclusive" in text.lower()


def test_a_crashed_gate_also_blocks(text: str) -> None:
    """A gate that cannot tell "the code got worse" from "the gate crashed"
    would let the second one through."""
    assert 'code" != "0"' in text
    assert "did not complete" in text


# --- supply chain -----------------------------------------------------------


def test_every_action_is_pinned_to_a_sha(workflow: dict) -> None:
    for step in steps(workflow):
        uses = step.get("uses")
        if not uses:
            continue
        _name, _, ref = uses.partition("@")
        assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), uses


def test_it_pulls_in_no_third_party_actions(workflow: dict) -> None:
    """A workflow that does inherits that action's supply chain on behalf of
    everyone who copies this file."""
    for step in steps(workflow):
        uses = step.get("uses")
        if uses:
            assert uses.startswith("actions/"), uses


def test_it_asks_for_no_more_permission_than_it_needs(workflow: dict) -> None:
    """It reads code and reports through the job summary. It writes nothing."""
    assert workflow["permissions"] == {"contents": "read"}


# --- it says why, not just what ---------------------------------------------


def test_the_file_explains_why_a_pr_gate_is_not_enough(text: str) -> None:
    """Someone will ask why this exists when `pr-reliability.yml` already does."""
    assert "each harmless can be a regression together" in text


def test_the_metrics_it_gates_on_all_exist(text: str) -> None:
    """A metric name with a typo would silently narrow the gate to nothing."""
    from tooltrace.analysis.pr_report import METRICS

    for metric in declared_metrics(text):
        assert metric in METRICS, metric
