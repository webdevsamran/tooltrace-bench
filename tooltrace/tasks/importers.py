"""Bring a task in from SWE-bench, BFCL, tau-bench or AgentBench.

Every one of these measures something real and none of them measures what this
project measures, so a converted task is **not** the original task. The value of
this module is less the conversion than the loss report attached to it: a
silently converted SWE-bench instance that scores 0.4 here tells a reader
nothing unless they know which half of the original grading survived.

## What each one is, and what does not come across

**SWE-bench** gives a repository at a commit, an issue, and a *test patch*. Its
oracle is "do the hidden tests pass after your patch". That translates well --
`tests_pass` is the same shape -- but the repository does not: this project's
sandbox is a temp workspace with declared starting files, not a checkout of
Django at a specific SHA. The converted task carries the issue and the test
command and **cannot fetch the repository**, so it is a draft that a human has
to point at a real checkout.

**BFCL** gives a prompt, a function catalogue and an expected call. Nothing is
executed: the grade is a structural match on the emitted call. That maps exactly
onto `tool_call_match`, and the conversion is close to lossless -- but it stays a
*trajectory-only* task. There is no workspace to assert on, because there was
never any side effect to observe.

**tau-bench** gives a multi-turn conversation with a simulated user and a
database, graded on the final database state. The conversation converts; the
simulated user does not, because it is an LLM this project does not run. The
converted task is single-turn unless the pack's adversarial-user machinery is
wired to it by hand.

**AgentBench** spans eight environments with per-environment graders. Only the
OS and DB environments have anything like a declarative oracle; the rest grade
with a model or a bespoke checker. Those are marked unconvertible rather than
approximated.

Nothing here fetches anything. Every importer takes a record you already have.
"""

from __future__ import annotations

import re
from typing import Any

SWE_BENCH = "swe-bench"
BFCL = "bfcl"
TAU_BENCH = "tau-bench"
AGENTBENCH = "agentbench"

FORMATS = (SWE_BENCH, BFCL, TAU_BENCH, AGENTBENCH)

#: A converted task is always a draft. Nothing here produces a task that should
#: run unreviewed: the conversions that lose the most are exactly the ones whose
#: output looks most complete.
DRAFT_MARKER = "TODO"


def _slug(text: str) -> str:
    """A task id fragment: lowercase, alphanumerics and dashes only."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return cleaned or "unnamed"


def _draft(
    task_id: str,
    *,
    objective: str,
    allowed_tools: list[str],
    assertions: list[dict[str, Any]],
    source: str,
    losses: list[str],
    todos: list[str],
    starting_workspace: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "id": task_id,
        "version": "0.1.0",
        "category": "imported",
        "objective": objective,
        "allowed_tools": allowed_tools,
        "assertions": assertions,
        "starting_workspace": starting_workspace or {},
        "network_policy": "disabled",
        "metadata": {
            "imported_from": source,
            # Carried on the task rather than printed once, so a reader who
            # finds this file six months later still learns what it is not.
            "conversion_losses": losses,
            "todo": todos,
            "is_draft": True,
        },
    }


def from_swe_bench(record: dict[str, Any]) -> dict[str, Any]:
    """A SWE-bench instance as a draft task.

    The oracle survives -- hidden tests passing is the same shape as
    `tests_pass`. The *repository* does not: this sandbox is a temp workspace
    with declared files, not a checkout at a SHA, and nothing here will clone
    one. So the converted task names the repository and commit and leaves
    fetching it to a human.
    """
    instance = str(record.get("instance_id") or record.get("id") or "unnamed")
    repo = str(record.get("repo") or "")
    commit = str(record.get("base_commit") or record.get("environment_setup_commit") or "")
    problem = str(record.get("problem_statement") or record.get("issue") or "").strip()
    test_command = str(record.get("test_cmd") or "pytest")

    return _draft(
        f"imported/swe-{_slug(instance)}",
        objective=(problem or f"Resolve the issue described in {instance}."),
        allowed_tools=["read_file", "search_text", "patch_file", "write_file", "test_runner"],
        assertions=[
            {
                "type": "tests_pass",
                "params": {"path": ".", "min_ratio": 1.0},
                "weight": 1.0,
                "description": "the hidden tests pass, which is SWE-bench's own oracle",
            }
        ],
        source=SWE_BENCH,
        losses=[
            "The repository is not fetched. SWE-bench grades a patch against a checkout at a "
            f"specific commit ({repo}@{commit or 'unknown'}); this sandbox is a temp workspace "
            "with declared starting files and will not clone one.",
            "The FAIL_TO_PASS / PASS_TO_PASS split is collapsed into one pass ratio. SWE-bench "
            "distinguishes tests that must start passing from tests that must keep passing, "
            "and a single ratio cannot express a regression in the second set.",
        ],
        todos=[
            f"{DRAFT_MARKER}: point `starting_workspace` at a checkout of {repo or 'the repo'} "
            f"at {commit or 'the base commit'}, or run this against a prepared image.",
            f"{DRAFT_MARKER}: the instance runs its tests with `{test_command}`; the assertion "
            "above uses this project's pytest runner, so change it if that is wrong.",
            f"{DRAFT_MARKER}: split the assertion if you need PASS_TO_PASS enforced separately.",
        ],
    )


def from_bfcl(record: dict[str, Any]) -> dict[str, Any]:
    """A BFCL case as a trajectory-only task.

    The closest of the four, because BFCL's grading -- a structural match on the
    emitted call, nothing executed -- is exactly what `tool_call_match` does.
    What stays absent is a workspace: there was never a side effect to observe,
    so the converted task asserts on the trace alone and says so.
    """
    case_id = str(record.get("id") or record.get("question_id") or "unnamed")
    question = record.get("question")
    if isinstance(question, list):
        prompt = " ".join(
            str(turn.get("content", "")) for turn in question if isinstance(turn, dict)
        ).strip()
    else:
        prompt = str(question or "").strip()

    expected = record.get("ground_truth") or record.get("answer") or []
    calls = expected if isinstance(expected, list) else [expected]
    shapes: list[dict[str, Any]] = []
    for call in calls:
        if isinstance(call, dict) and call:
            name = next(iter(call))
            arguments = call[name] if isinstance(call[name], dict) else {}
            shapes.append({"tool": str(name), "args": sorted(arguments)})

    functions = record.get("function") or record.get("functions") or []
    tool_names = [
        str(f.get("name")) for f in functions if isinstance(f, dict) and f.get("name")
    ] or ["read_file"]

    return _draft(
        f"imported/bfcl-{_slug(case_id)}",
        objective=prompt or f"Answer BFCL case {case_id} with the correct tool call.",
        allowed_tools=tool_names,
        assertions=(
            [
                {
                    "type": "tool_call_match",
                    "params": {"ordered": True, "expected": shapes},
                    "weight": 1.0,
                    "description": "the expected call, matched structurally as BFCL grades it",
                }
            ]
            if shapes
            else []
        ),
        source=BFCL,
        losses=[
            "No workspace and no side effects. BFCL executes nothing, so there is no end state "
            "to assert on and this task scores the trajectory only.",
            "The tools named in `allowed_tools` are BFCL's function catalogue and are almost "
            "certainly not registered here. Until they are, every call fails as an unknown "
            "tool -- which `tooltrace lint` reports.",
        ],
        todos=[
            f"{DRAFT_MARKER}: register the functions this case names, or map them onto tools "
            "that exist here.",
            f"{DRAFT_MARKER}: BFCL matches argument *values* for some categories; this "
            "conversion matches names and order. Tighten the expectation if the case needs it.",
        ],
    )


def from_tau_bench(record: dict[str, Any]) -> dict[str, Any]:
    """A tau-bench case, minus the simulated user.

    The conversation and the target database state convert. The user does not:
    tau-bench's user is an LLM, and this project does not run one. What comes
    across is the first turn and the final-state check, which is a strictly
    easier task than the original.
    """
    case_id = str(record.get("id") or record.get("task_id") or "unnamed")
    instruction = str(record.get("instruction") or record.get("user_instruction") or "").strip()
    outputs = record.get("outputs") or record.get("expected_outputs") or []

    assertions = [
        {
            "type": "file_contains",
            "params": {"path": "result.json", "text": str(value)},
            "weight": 1.0,
            "description": f"the expected value {value!r} appears in the final state",
        }
        for value in (outputs if isinstance(outputs, list) else [outputs])
        if str(value).strip()
    ]

    return _draft(
        f"imported/tau-{_slug(case_id)}",
        objective=instruction or f"Complete tau-bench case {case_id}.",
        allowed_tools=["read_file", "write_file"],
        assertions=assertions,
        source=TAU_BENCH,
        losses=[
            "The simulated user is gone. tau-bench grades an agent across several turns with "
            "an LLM playing a customer who changes their mind; this converts the first "
            "instruction only, which is a strictly easier task.",
            "The database is gone. The final-state check becomes a file assertion, which is "
            "the same question asked of a different substrate.",
        ],
        todos=[
            f"{DRAFT_MARKER}: wire this to the `adversarial-user` pack's intervention "
            "machinery if you need the multi-turn behaviour tau-bench actually measures.",
            f"{DRAFT_MARKER}: supply a `starting_workspace` standing in for the database.",
        ],
    )


#: AgentBench environments whose grading is declarative enough to convert.
#: The rest use a model judge or a bespoke checker, and are refused rather than
#: approximated -- an approximated oracle is a task that scores something nobody
#: chose.
CONVERTIBLE_AGENTBENCH = frozenset({"os", "db", "dbbench", "operating-system"})


def from_agentbench(record: dict[str, Any]) -> dict[str, Any]:
    """An AgentBench case, when its environment has a declarative oracle."""
    environment = str(record.get("environment") or record.get("env") or "").lower()
    case_id = str(record.get("id") or "unnamed")
    description = str(record.get("description") or record.get("instruction") or "").strip()

    if environment not in CONVERTIBLE_AGENTBENCH:
        return {
            "convertible": False,
            "environment": environment or "(not declared)",
            "reason": (
                f"AgentBench's {environment or 'unnamed'} environment grades with a model judge "
                "or a bespoke checker rather than a declarative oracle. Approximating it would "
                "produce a task that scores something nobody chose; only the OS and DB "
                "environments convert"
            ),
        }

    expected = str(record.get("expected") or record.get("answer") or "").strip()
    return _draft(
        f"imported/agentbench-{_slug(environment)}-{_slug(case_id)}",
        objective=description or f"Complete AgentBench {environment} case {case_id}.",
        allowed_tools=["shell", "read_file", "write_file"],
        assertions=(
            [
                {
                    "type": "file_contains",
                    "params": {"path": "answer.txt", "text": expected},
                    "weight": 1.0,
                    "description": "the expected answer",
                }
            ]
            if expected
            else []
        ),
        source=AGENTBENCH,
        losses=[
            "The environment image is gone. AgentBench's OS tasks run in a prepared container "
            "and this sandbox is a temp workspace, so the starting state has to be declared "
            "by hand.",
            "Interactive grading is gone. Where AgentBench checks state during the episode, "
            "this checks it at the end.",
        ],
        todos=[
            f"{DRAFT_MARKER}: declare the starting state this case assumes.",
            f"{DRAFT_MARKER}: confirm the answer format -- this writes it to `answer.txt`.",
        ],
    )


IMPORTERS = {
    SWE_BENCH: from_swe_bench,
    BFCL: from_bfcl,
    TAU_BENCH: from_tau_bench,
    AGENTBENCH: from_agentbench,
}


def convert(source: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert a batch, keeping the refusals visible alongside the drafts."""
    if source not in IMPORTERS:
        raise ValueError(f"unknown source {source!r}; expected one of {', '.join(FORMATS)}")
    importer = IMPORTERS[source]

    tasks: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for record in records:
        converted = importer(record)
        if converted.get("convertible") is False:
            refused.append(converted)
        else:
            tasks.append(converted)

    return {
        "source": source,
        "records": len(records),
        "tasks": tasks,
        "refused": refused,
        "all_drafts": True,
        "statement": (
            f"{len(tasks)} draft task(s) from {len(records)} {source} record(s)"
            + (f"; {len(refused)} refused as unconvertible" if refused else "")
            + ". **Every one is a draft.** A converted task is not the original task: what "
            "each conversion loses is recorded in its own metadata, and the conversions that "
            "lose the most are the ones whose output looks most complete."
        ),
    }
