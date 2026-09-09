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
_EXPECTED_PARAM_KEYS = ("text", "expected", "contains", "value", "equals")

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
    return problems


def leaked_expected_values(task: dict[str, Any]) -> list[str]:
    """An expected value visible in the prompt makes the score transcription."""
    haystack = " ".join(
        [str(task.get("objective") or "")]
        + [str(v) for v in (task.get("starting_workspace") or {}).values()]
    ).lower()
    if not haystack.strip():
        return []
    leaked = []
    for assertion in task.get("assertions") or []:
        params = assertion.get("params") or {}
        for key in _EXPECTED_PARAM_KEYS:
            value = params.get(key)
            if not isinstance(value, str) or len(value) < _MIN_LEAK_LENGTH:
                continue
            # `file_not_contains` asserts something is *absent*; the value
            # appearing in the starting workspace is the entire point of it.
            if str(assertion.get("type", "")).endswith("not_contains"):
                continue
            if value.lower() in haystack:
                leaked.append(
                    f"{assertion.get('type')}: expected value {value!r} appears in the prompt"
                )
    return leaked


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
