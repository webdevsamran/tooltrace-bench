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

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_ACTION = _ROOT / "action.yml"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def load_ref_checker() -> Any:
    """Import `scripts/check_action_refs.py`, which is not a package module."""
    spec = importlib.util.spec_from_file_location(
        "ttb_check_action_refs", _ROOT / "scripts" / "check_action_refs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


# --- the action has to run somewhere, not only parse -------------------------


def test_ci_actually_runs_the_action() -> None:
    """Every test above this line reads YAML. None executes the composite body.

    The argument assembly, the inline Python, the `GITHUB_OUTPUT` writes and the
    threshold logic had never run in any job, in this repository or anywhere
    else, while the docs told people to depend on them.
    """
    body = _CI.read_text(encoding="utf-8")
    assert "uses: ./" in body, "no CI job runs the action itself"


def test_ci_proves_the_threshold_can_fail_a_build() -> None:
    """A gate nobody has watched fire is a gate nobody knows fires."""
    body = _CI.read_text(encoding="utf-8")
    assert "min-success-rate" in body
    assert "continue-on-error: true" in body


def test_a_failed_install_explains_itself() -> None:
    """The default path is `pip install tooltrace-bench`, and that 404s today.

    A bare pip failure in somebody else's CI log names neither the cause nor a
    way forward.
    """
    body = _ACTION.read_text(encoding="utf-8")
    assert "::error::could not install" in body
    assert "install: false" in body, "the message does not name the way out"


def test_a_clean_run_is_not_reported_as_failures() -> None:
    """`none` is the taxonomy bucket for runs that did not fail.

    Eight clean runs rendered as "Failures: none x 8" in the job summary.
    """
    assert 'if k != "none"' in _ACTION.read_text(encoding="utf-8")


# --- the documented recipes ---------------------------------------------------


def test_no_documented_recipe_points_at_the_only_release_tag() -> None:
    """`v0.3.0` is the one tag this project has cut, and it predates the action.

    `uses: webdevsamran/tooltrace-bench@v0.3.0` fails with "Can't find
    'action.yml'" before a task runs. Checked here as well as over the network
    in `scripts/check_action_refs.py`, because this half needs neither.
    """
    module = load_ref_checker()
    offenders = []
    for path in module.DOCS:
        if not path.is_file():
            continue
        for lineno, ref, _ in module.recipes(path):
            if ref == "v0.3.0":
                offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], f"these reference a tag with no action in it: {offenders}"


def _doc(tmp_path: Path, *body: str) -> Path:
    path = tmp_path / "recipe.md"
    path.write_text("```yaml\n" + "\n".join(body) + "\n```\n", encoding="utf-8")
    return path


def test_the_checker_sees_a_recipe_that_assumes_pypi(tmp_path: Path) -> None:
    module = load_ref_checker()
    doc = _doc(
        tmp_path,
        "      - uses: webdevsamran/tooltrace-bench@main",
        "        with:",
        "          agent: scripted",
    )
    ((lineno, ref, opts_out),) = module.recipes(doc)
    assert (lineno, ref, opts_out) == (2, "main", False)


def test_an_explicit_install_false_is_an_opt_out(tmp_path: Path) -> None:
    module = load_ref_checker()
    doc = _doc(
        tmp_path,
        "      - uses: webdevsamran/tooltrace-bench@main",
        "        with:",
        '          install: "false"',
    )
    assert module.recipes(doc)[0][2] is True


def test_a_source_version_is_an_opt_out(tmp_path: Path) -> None:
    """Leaving `install` alone is fine when `version:` names a checkout."""
    module = load_ref_checker()
    doc = _doc(
        tmp_path,
        "      - uses: webdevsamran/tooltrace-bench@main",
        "        with:",
        "          version: tooltrace-bench @ git+https://github.com/o/r@main",
    )
    assert module.recipes(doc)[0][2] is True


def test_a_later_step_is_not_read_as_this_step(tmp_path: Path) -> None:
    """Otherwise one opted-out step would excuse every recipe on the page."""
    module = load_ref_checker()
    doc = _doc(
        tmp_path,
        "      - uses: webdevsamran/tooltrace-bench@main",
        "        with:",
        "          agent: scripted",
        "      - uses: actions/checkout@v5",
        "        with:",
        '          install: "false"',
    )
    assert module.recipes(doc)[0][2] is False
