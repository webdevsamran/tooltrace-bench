"""Every document must cite code that exists, not just `feature-status.md`.

The path check lived inside `tests/test_feature_status_is_truthful.py` and
scanned exactly one file. So `docs/differentiators.md` -- whose entire job is to
state what this project does that others do not -- cited four modules that do
not exist, including `scoring/judges.py`, which describes a capability that has
never existed. `scripts/check_docs_links.py` did not catch them because it
validates markdown `[](...)` links, not backticked paths.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent


def _checker() -> Any:
    path = _ROOT / "scripts" / "check_doc_code_refs.py"
    spec = importlib.util.spec_from_file_location("check_doc_code_refs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_documented_path_resolves() -> None:
    assert _checker().main() == 0


def test_the_checker_reports_a_path_that_does_not_exist() -> None:
    """Non-vacuousness: a checker that finds nothing must be able to find something."""
    module = _checker()
    refs = module.iter_refs("see `tooltrace/nope/missing.py` for details")
    assert refs == ["tooltrace/nope/missing.py"]
    assert not module.resolves("tooltrace/nope/missing.py")


def test_prose_and_placeholders_are_not_mistaken_for_paths() -> None:
    """A checker that cries wolf gets ignored, which is worse than none."""
    module = _checker()
    for token in (
        "result.json",  # a bundle member, not a repo path
        "feat/my-task-pack",  # a branch name
        "fileops/copy-and-rename",  # a task id
        "pkg:pypi/",  # a purl prefix
        "I/P",  # a grade
        "runs/<bundle>.tooltrace",  # a placeholder
        "ScoringContract.judge_required",  # a symbol
    ):
        assert not module.looks_like_path(token), f"{token!r} should not be treated as a path"


def test_corrections_and_code_blocks_are_exempt() -> None:
    """A dated correction says "this used to cite X"; that is history, not a claim."""
    module = _checker()
    text = "> it cited `tooltrace/gone/old.py`\n\n```\n`tooltrace/also/gone.py`\n```\nlive text\n"
    assert module.iter_refs(module.strip_uncheckable(text)) == []


def test_runtime_workspace_paths_are_declared_not_silently_widened() -> None:
    """The egress log lives in a sandbox workspace, never in the repository.

    Declaring that category is honest. Loosening `looks_like_path` until
    nothing fails would have hidden real broken citations along with it.
    """
    module = _checker()
    assert module.RUNTIME_PREFIXES, "the exemption list must be explicit"
    assert not module.looks_like_path(".tooltrace_egress/requests.jsonl")
    # ...and the loosening must not have swallowed ordinary repository paths.
    assert module.looks_like_path("tooltrace/tools/sink.py")
    assert not module.resolves("tooltrace/nope/missing.py")
