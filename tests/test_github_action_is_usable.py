"""The published GitHub Action must be well-formed and honest.

There was no action at all, which is most of why the CI integration this project
is built for did not happen: telling someone to write their own workflow is a
higher bar than pointing at one line.

The action deliberately pulls in **no third-party actions**. A composite action
that bundles `setup-python` inherits that action's supply chain on behalf of
every caller, and pins it on their behalf too — in a repository whose CI already
enforces SHA pinning with verified version comments, quietly making that
decision for downstream users would be the wrong trade. The caller sets up
Python with whatever policy they already apply.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_ACTION = _ROOT / "action.yml"


@pytest.fixture(scope="module")
def action() -> dict:
    assert _ACTION.is_file(), "action.yml is missing"
    return yaml.safe_load(_ACTION.read_text(encoding="utf-8"))


def test_it_is_a_composite_action_with_a_name_and_description(action: dict) -> None:
    assert action["name"]
    assert action["description"].strip()
    assert action["runs"]["using"] == "composite"


def test_it_pulls_in_no_third_party_actions(action: dict) -> None:
    """Otherwise every caller inherits a supply chain we chose for them."""
    uses = [step.get("uses") for step in action["runs"]["steps"] if step.get("uses")]
    assert uses == [], f"the action now depends on {uses}; that decision belongs to the caller"


def test_every_input_documents_itself(action: dict) -> None:
    for name, spec in action["inputs"].items():
        assert spec.get("description", "").strip(), f"input {name} has no description"
        assert "default" in spec, f"input {name} has no default; required inputs surprise callers"


def test_the_ci_relevant_inputs_exist(action: dict) -> None:
    """These are what make a per-pull-request run affordable and gated."""
    for name in ("agent", "runs", "limit", "shuffle", "seed", "min-success-rate"):
        assert name in action["inputs"], f"input {name} is missing"


def test_outputs_are_wired_to_a_step(action: dict) -> None:
    step_ids = {step.get("id") for step in action["runs"]["steps"] if step.get("id")}
    for name, spec in action["outputs"].items():
        value = spec["value"]
        assert "steps." in value, f"output {name} is not produced by a step"
        referenced = value.split("steps.")[1].split(".")[0]
        assert referenced in step_ids, f"output {name} references unknown step {referenced!r}"


def test_it_reports_whether_the_run_was_a_subset(action: dict) -> None:
    """A trimmed run must never be reported as a full one."""
    assert "is-subset" in action["outputs"]
    body = _ACTION.read_text(encoding="utf-8")
    assert "This is a subset, not a full run." in body


def test_it_does_not_let_a_tiny_sample_look_conclusive(action: dict) -> None:
    """A green check on n=2 should not read like evidence."""
    body = _ACTION.read_text(encoding="utf-8")
    assert "::warning::" in body and "small sample" in body


def test_it_refuses_a_threshold_it_cannot_evaluate(action: dict) -> None:
    """No measured rate must fail loudly, not pass by default."""
    body = _ACTION.read_text(encoding="utf-8")
    assert "no success rate was measured" in body


def test_the_documented_flags_exist_on_the_cli(action: dict) -> None:
    """The action's whole job is calling this CLI; the flags have to be real."""
    from tooltrace.cli.main import build_parser

    subparsers = [
        a
        for a in build_parser()._actions
        if isinstance(getattr(a, "choices", None), dict) and "benchmark" in a.choices
    ]
    assert subparsers, "could not locate the subcommand table"
    benchmark = subparsers[0].choices["benchmark"]
    flags = {opt for action_ in benchmark._actions for opt in action_.option_strings}
    for flag in (
        "--agent",
        "--runs",
        "--task",
        "--limit",
        "--shuffle",
        "--seed",
        "--out",
        "--json",
    ):
        assert flag in flags, f"action.yml passes {flag}, which benchmark does not accept"
