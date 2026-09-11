"""Anti-gaming checks that actually inspect something.

`anti_gaming_checks` in `tooltrace/analysis/core.py` has shipped since 0.2.0 and
reads `assertion_results`, `declared_assertions`, `task_hashes`,
`harness_sha256` and `expected_harness_sha256` off the result it is handed.
`EvalResult` has none of those fields. Called on a real result it therefore
returns `{"ok": True, "problems": []}` having performed **zero** checks — it is
green because it looked at nothing.

Wiring it up as-is would have been worse than leaving it unwired: a permanently
passing integrity check is the "CI step named for a validation it never
performed" that this repository has already had to correct once. So this module
builds the record it needs out of data a bundle really contains, and adds the
checks that only a bundle can support.

Three questions, each answerable from a `.tooltrace` directory:

- **Were all the declared assertions actually scored?** A run that quietly drops
  a failing assertion scores higher than it earned. The task declares its
  assertions; `scoring.json` records the components that were evaluated.
- **Was the task modified after publication?** The bundle embeds the exact
  `task.yaml` used. If it differs from the task of the same id in the installed
  pack, the fixture or its assertions changed — which invalidates any comparison
  against results produced from the published task.
- **Was the answer leaked to the agent?** If an assertion's expected value
  appears verbatim in the objective or in the starting workspace, the task tells
  the agent what to write and the score measures transcription.

What this does not do: it cannot detect a harness modified before the run, since
no harness hash is recorded in the bundle. That is stated rather than implied —
`harness_hash_recorded` is reported as `False` so a reader knows the check was
not performed rather than performed and passed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from tooltrace.tasks.governance import sha256_text

#: Assertion params whose value is the thing the agent is supposed to produce.
#: `expected_csv` was missing, so every `csv_equals` assertion escaped the
#: leak check entirely -- a whole scorer's worth of expected values could sit
#: in a prompt unnoticed. Keys are the union of what the built-in scorers
#: read, not a guess.
_EXPECTED_PARAM_KEYS = (
    "text",
    "expected",
    "expected_csv",
    "contains",
    "value",
    "equals",
    "reference",
    "defines",
)

#: Below this length an "expected" value is too generic for its appearance in a
#: prompt to mean anything — a task about writing "ok" into a file is not leaking.
_MIN_LEAK_LENGTH = 6


def _load(bundle_dir: Path, name: str) -> Any:
    path = bundle_dir / name
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) if name.endswith((".yaml", ".yml")) else json.loads(text)


def declared_vs_scored(task: dict[str, Any], scoring: dict[str, Any]) -> list[str]:
    """Every declared assertion must appear in the recorded score."""
    declared = task.get("assertions") or []
    if not declared:
        return []
    labels = {
        str(a.get("description") or a.get("type") or f"assertion-{i}")
        for i, a in enumerate(declared)
    }
    scored = set((scoring.get("score") or {}).get("components") or {})
    missing = sorted(labels - scored)
    if missing:
        return [f"declared assertions absent from the score: {missing}"]
    return []


def task_matches_published(task: dict[str, Any], installed: dict[str, Any] | None) -> list[str]:
    """The task in the bundle must match the task of that id on disk."""
    if installed is None:
        return []
    problems = []
    if sha256_text(json.dumps(task.get("assertions"), sort_keys=True)) != sha256_text(
        json.dumps(installed.get("assertions"), sort_keys=True)
    ):
        problems.append("assertions differ from the published task of the same id")
    if sha256_text(json.dumps(task.get("starting_workspace"), sort_keys=True)) != sha256_text(
        json.dumps(installed.get("starting_workspace"), sort_keys=True)
    ):
        problems.append("starting workspace differs from the published task of the same id")
    # Attachments are workspace content the run depended on, so a swapped
    # screenshot is a swapped task. Without this the one file an agent was
    # scored against could be replaced and the bundle would still verify.
    # `or []` on both sides: bundles recorded before this field existed carry no
    # `attachments` key at all, and `null` is not a different value from "none"
    # -- reporting those as tampered would make every published bundle fail.
    if sha256_text(json.dumps(task.get("attachments") or [], sort_keys=True)) != sha256_text(
        json.dumps(installed.get("attachments") or [], sort_keys=True)
    ):
        problems.append("attachments differ from the published task of the same id")
    return problems


def _expected_values(assertion: dict[str, Any]) -> list[str]:
    """Literal values one assertion expects, long enough to be meaningful."""
    params = assertion.get("params") or {}
    values = []
    for key in _EXPECTED_PARAM_KEYS:
        value = params.get(key)
        if isinstance(value, str) and len(value) >= _MIN_LEAK_LENGTH:
            values.append(value)
    any_of = params.get("any_of")
    if isinstance(any_of, list):
        values.extend(
            str(v) for v in any_of if isinstance(v, str) and len(str(v)) >= _MIN_LEAK_LENGTH
        )
    return values


def _is_preservation_assertion(assertion: dict[str, Any], workspace: dict[str, Any]) -> bool:
    """Does this assertion require existing content to *stay* rather than appear?

    `test-repair/fix-test-expectation` asserts that `calc.py` still contains
    `return a + b` -- "implementation untouched". The value being present in the
    starting workspace is the entire point of the assertion, exactly as it is for
    `file_not_contains`, which was already exempt. Flagging it as a leak is
    backwards: it would push an author to delete the assertion that stops an
    agent from "fixing" a test by rewriting the code under it.

    Provable from the task alone: the assertion targets a starting file, and the
    value is already in *that* file.
    """
    path = (assertion.get("params") or {}).get("path")
    if not isinstance(path, str) or path not in workspace:
        return False
    existing = str(workspace.get(path) or "").lower()
    return any(value.lower() in existing for value in _expected_values(assertion))


def _declared_extraction(task: dict[str, Any]) -> str:
    """A task's stated reason that its answer legitimately sits in its input.

    Retrieval, citation, redaction and hand-off tasks are all cases where the
    expected value appears in the workspace *because copying it is the skill*.
    `knowledge/cite-the-source` asks the agent to quote a value and cite where it
    came from; `legal/quote-the-clause-exactly` asks for a verbatim clause and
    fails a paraphrase. In both, "the answer is in the input" describes the task
    rather than a flaw in it.

    Structure cannot separate that from a genuine leak -- both look like a value
    in a file the agent reads -- so the task declares it, and the declaration is
    reported rather than silently honoured. A reader can list every task claiming
    the exemption, which is the property that keeps it from becoming a way to
    switch the check off.
    """
    metadata = task.get("metadata")
    reason = (metadata or {}).get("expected_value_in_input") if isinstance(metadata, dict) else None
    return str(reason) if reason else ""


def expected_value_report(task: dict[str, Any]) -> dict[str, Any]:
    """Where each expected value is visible, classified by what that means.

    The original check searched the objective and the starting workspace
    together, and those are not the same thing.

    The **objective is the specification**. A task that says 'correct the line so
    it reads "status: ready"' has *told* the agent what to produce; an assertion
    checking that it did is not transcription, it is the task. Whatever the
    objective says is by definition given, and flagging it asks authors to write
    vaguer objectives, which makes tasks worse rather than more rigorous.

    The **starting workspace is input data**. An expected value found there and
    not stated in the objective is the dangerous case: the answer is sitting in a
    file the agent reads, so a task that looks like a transformation can be
    passed by a copy. That is what anti-gaming is about, and it is the only class
    that fails integrity.
    """
    workspace = task.get("starting_workspace") or {}
    objective = f"{task.get('objective') or ''} {task.get('description') or ''}".lower()
    workspace_text = " ".join(str(v) for v in workspace.values()).lower()
    extraction_reason = _declared_extraction(task)

    in_workspace: list[str] = []
    in_objective: list[str] = []
    preserved: list[str] = []

    for assertion in task.get("assertions") or []:
        kind = str(assertion.get("type", ""))
        # `file_not_contains` asserts something is *absent*; its value appearing
        # in the starting workspace is the entire point of it.
        if kind.endswith("not_contains"):
            continue
        if _is_preservation_assertion(assertion, workspace):
            preserved.extend(
                f"{kind}: {v!r} must remain unchanged" for v in _expected_values(assertion)
            )
            continue
        for value in _expected_values(assertion):
            lowered = value.lower()
            if lowered in workspace_text and lowered not in objective:
                in_workspace.append(
                    f"{kind}: expected value {value!r} is already in the starting workspace"
                )
            elif lowered in objective:
                in_objective.append(f"{kind}: expected value {value!r} is stated in the objective")

    declared_extraction = in_workspace if extraction_reason else []
    return {
        # The only class that fails integrity. A task that declares itself an
        # extraction task moves its findings to `declared_extraction`, where they
        # stay visible.
        "leaked_to_workspace": [] if extraction_reason else in_workspace,
        "declared_extraction": declared_extraction,
        "extraction_reason": extraction_reason,
        # Reported so an author can see it, never a failure: the objective is the
        # specification, and a task is entitled to state its target.
        "stated_in_objective": in_objective,
        "preservation_assertions": preserved,
    }


def leaked_expected_values(task: dict[str, Any]) -> list[str]:
    """Expected values an agent could copy out of its own input.

    Narrowed from "visible anywhere in the prompt" to "sitting in the starting
    workspace and not stated in the objective" -- see `expected_value_report` for
    why those are different questions. The wider version flagged two shipped
    tasks that are correctly designed, and a check that fires on correct design
    trains people to ignore it.
    """
    return list(expected_value_report(task)["leaked_to_workspace"])


def check_bundle_integrity(
    bundle_dir: Path, installed_task: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run every anti-gaming check that this bundle's contents can support."""
    task = _load(bundle_dir, "task.yaml") or {}
    scoring = _load(bundle_dir, "scoring.json") or {}

    problems: list[str] = []
    problems += declared_vs_scored(task, scoring)
    problems += task_matches_published(task, installed_task)
    problems += leaked_expected_values(task)

    return {
        "ok": not problems,
        "problems": problems,
        "checks_run": [
            "declared_assertions_were_scored",
            "task_matches_published" if installed_task is not None else None,
            "expected_values_not_leaked_to_the_prompt",
        ],
        # Stated rather than implied: no harness hash is recorded in a bundle,
        # so a harness modified before the run is outside what this can see.
        "harness_hash_recorded": False,
    }


def installed_task_for(task_id: str) -> dict[str, Any] | None:
    """The published task of this id, if the pack is installed here."""
    from tooltrace.tasks import load_all_tasks

    for task in load_all_tasks():
        if task.id == task_id:
            return dict(task.model_dump(mode="json"))
    return None
