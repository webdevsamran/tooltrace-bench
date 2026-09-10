"""A system card from run data, and an audit of your own evidence.

Two documents nobody can write honestly by hand.

**The system card** (`build_card`) is a description of what an agent can and
cannot do. Written by hand it becomes marketing: the capabilities section fills
up, the limitations section reads "may occasionally make mistakes", and the
unmeasured section does not exist. Generated from runs, every line has a run
behind it — and the section that is usually empty is the one this generator can
fill best, because *what was never measured* is exactly what a benchmark knows.

**The self-audit** (`audit_evidence`) turns the EU AI Act's operative phrase back
on this project's own output. Organisations must *demonstrate* compliance rather
than claim it, and the natural next question is whether the evidence you hold
would actually demonstrate anything. It answers with a checklist and a list of
gaps.

It deliberately does **not** produce a percentage. "Evidence completeness: 73%"
is a number that gets put on a slide, and there is no defensible weighting that
makes 73% mean something to a regulator. A checklist with named gaps cannot be
summarised into a grade, which is the point.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

#: Below this, a success rate is not a capability claim. Matches the threshold
#: `analysis/power.py` uses for the same reason.
MIN_RUNS_FOR_A_CLAIM = 10


def _grouped(runs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(str(run.get("task_id", "")), []).append(run)
    return grouped


def build_card(
    runs: list[dict[str, Any]],
    *,
    agent: str,
    generated_at: str,
    security: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A system card for one agent, from the runs that exist.

    Every capability line names its sample size, and a task run fewer than
    `MIN_RUNS_FOR_A_CLAIM` times appears under "insufficiently measured" rather
    than under capabilities or limitations. A 3-run 100% is not a capability, and
    a 3-run 0% is not a limitation.
    """
    mine = [r for r in runs if str(r.get("agent")) == agent]
    grouped = _grouped(mine)

    capabilities: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    undersampled: list[dict[str, Any]] = []

    for task_id, task_runs in sorted(grouped.items()):
        successes = sum(1 for r in task_runs if r.get("success"))
        rate = successes / len(task_runs)
        entry = {
            "task": task_id,
            "runs": len(task_runs),
            "success_rate": round(rate, 4),
        }
        if len(task_runs) < MIN_RUNS_FOR_A_CLAIM:
            undersampled.append(entry)
        elif rate >= 0.9:
            capabilities.append(entry)
        elif rate <= 0.5:
            limitations.append(entry)
        else:
            entry["note"] = "succeeds sometimes; neither a capability nor a limitation"
            undersampled.append(entry)

    failures = Counter(
        str(r.get("failure_reason"))
        for r in mine
        if not r.get("success") and r.get("failure_reason")
    )

    unmeasured = _unmeasured_axes(mine, security, coverage)

    return {
        "schema": "tooltrace-system-card/1",
        "agent": agent,
        "generated_at": generated_at,
        "runs": len(mine),
        "tasks": len(grouped),
        "capabilities": capabilities,
        "limitations": limitations,
        # The middle ground, kept as its own section because collapsing it into
        # either neighbour is how a card starts overclaiming.
        "insufficiently_measured": undersampled,
        "failure_modes": [
            {"reason": reason, "runs": count} for reason, count in failures.most_common()
        ],
        # The section a hand-written card never has, and the one a benchmark is
        # uniquely able to fill.
        "not_measured": unmeasured,
        "statement": (
            "Generated from recorded runs. Every line has runs behind it and states how "
            "many. This describes behaviour on this project's task packs, on the hardware "
            "recorded in each bundle; it is not a description of the agent in general, and "
            "the 'not measured' section is as much a part of it as the rest."
        ),
    }


def _unmeasured_axes(
    runs: list[dict[str, Any]],
    security: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
) -> list[str]:
    """What this card cannot speak to, named specifically."""
    unmeasured: list[str] = []

    priced = [r for r in runs if ((r.get("usage") or {}).get("provider_cost_reported")) is not None]
    if not priced:
        unmeasured.append(
            "Cost. No run reported provider spend, so nothing here says what this agent costs."
        )

    attempts = int((security or {}).get("attempts") or 0)
    if attempts == 0:
        unmeasured.append("Adversarial resistance. No security task was run against this agent.")
    elif attempts < 30:
        unmeasured.append(
            f"Adversarial resistance beyond {attempts} attempt(s). That is far too few for "
            "the rate to be stable; read the interval, not the rate."
        )

    if coverage:
        missing = [
            f"{row['id']} ({row['label']})"
            for row in coverage.get("categories", [])
            if row.get("status") != "covered"
        ]
        if missing:
            unmeasured.append(
                "OWASP Agentic categories with no runnable task here: " + ", ".join(missing)
            )

    if not any((r.get("usage") or {}).get("model_time_ms") for r in runs):
        unmeasured.append(
            "Inference latency. No adapter reported model time, so the split between "
            "thinking and acting is unknown."
        )

    unmeasured.append(
        "Everything the task packs do not cover. A benchmark measures the failure modes it "
        "encodes and says nothing about the ones it does not."
    )
    return unmeasured


def render_card(card: dict[str, Any]) -> str:
    """A readable system card. The limits are not an appendix."""
    lines = [
        f"# System card: {card['agent']}",
        "",
        f"Generated {card['generated_at']} from {card['runs']} run(s) across "
        f"{card['tasks']} task(s).",
        "",
        f"> {card['statement']}",
        "",
        "## What it does reliably",
        "",
    ]
    if card["capabilities"]:
        lines += [
            f"- `{c['task']}`: {c['success_rate']:.0%} over {c['runs']} runs"
            for c in card["capabilities"]
        ]
    else:
        lines.append("- Nothing has enough runs behind it to claim reliability.")

    lines += ["", "## Where it fails", ""]
    if card["limitations"]:
        lines += [
            f"- `{limit['task']}`: {limit['success_rate']:.0%} over {limit['runs']} runs"
            for limit in card["limitations"]
        ]
    else:
        lines.append("- No task with enough runs behind it failed consistently.")

    if card["insufficiently_measured"]:
        lines += ["", "## Not measured enough to say", ""]
        lines += [
            f"- `{entry['task']}`: {entry['runs']} run(s)"
            + (f", {entry['note']}" if entry.get("note") else "")
            for entry in card["insufficiently_measured"]
        ]

    if card["failure_modes"]:
        lines += ["", "## How it fails", ""]
        lines += [f"- {mode['reason']}: {mode['runs']} run(s)" for mode in card["failure_modes"]]

    lines += ["", "## Not measured at all", ""]
    lines += [f"- {item}" for item in card["not_measured"]]
    return "\n".join(lines) + "\n"


# --- the self-audit ---------------------------------------------------------


def audit_evidence(
    *,
    bundles: list[dict[str, Any]],
    attested: int = 0,
    independently_attested: int = 0,
    security_attempts: int = 0,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Would the evidence you hold actually demonstrate anything?

    The EU AI Act's operative phrase is that an organisation must *demonstrate*
    compliance rather than claim it. This turns that back on the evidence itself.

    No score. "Evidence completeness: 73%" is a number that ends up on a slide,
    and there is no defensible weighting that makes it mean something to a
    regulator. A checklist with named gaps cannot be summarised into a grade,
    which is exactly why it is a checklist.
    """
    total = len(bundles)
    verified = sum(1 for b in bundles if b.get("verified"))
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str, gap: str = "") -> None:
        checks.append(
            {"check": name, "passed": passed, "detail": detail, "gap": "" if passed else gap}
        )

    check(
        "runs_exist",
        total > 0,
        f"{total} bundle(s)",
        "There is no evidence at all. Run something and keep the bundles.",
    )
    check(
        "every_bundle_verifies",
        total > 0 and verified == total,
        f"{verified} of {total} verify against their checksums",
        "A bundle that fails verification is not evidence; it is a file.",
    )
    check(
        "sample_is_large_enough_to_quote",
        total >= 30,
        f"{total} run(s)",
        f"{total} runs cannot support a stable rate. See `tooltrace power`.",
    )
    check(
        "reproduced_by_someone_else",
        independently_attested > 0,
        f"{independently_attested} independent attestation(s)",
        "Nobody but you has reproduced any of this. Reproducibility that nobody has "
        "exercised is a property you believe you have.",
    )
    check(
        "attested_at_all",
        attested > 0,
        f"{attested} attestation(s)",
        "No attestation exists, so the trust state of every bundle is LOCAL and means "
        "exactly that.",
    )
    check(
        "adversarial_evidence_exists",
        security_attempts > 0,
        f"{security_attempts} adversarial attempt(s)",
        "No security task was run. Robustness is unevidenced.",
    )
    if coverage:
        covered = int(coverage.get("covered") or 0)
        check(
            "security_coverage_is_broad",
            covered >= 5,
            f"{covered} of {coverage.get('total')} OWASP Agentic categories",
            f"Only {covered} of {coverage.get('total')} categories have a runnable task. "
            "The rest are unmeasured, which is not the same as safe.",
        )

    gaps = [c["gap"] for c in checks if not c["passed"]]
    return {
        "checks": checks,
        "passed": sum(1 for c in checks if c["passed"]),
        "total": len(checks),
        "gaps": gaps,
        # Deliberately not a percentage. See the docstring.
        "statement": (
            f"{sum(1 for c in checks if c['passed'])} of {len(checks)} evidence checks pass. "
            "This is a checklist, not a score: there is no weighting of these that would "
            "mean anything to a regulator, and a percentage would be quoted as though there "
            "were."
        ),
    }
