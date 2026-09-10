"""OWASP Agentic Top 10 coverage, generated from packs that actually run.

A coverage matrix is the easiest document in a security project to fake, and the
fake version is more damaging than no document: a table of ten rows with ten
ticks, hand-written, reviewed once, and wrong within a month. This one is
computed from the installed task packs every time it is asked for, so a category
is covered exactly when a runnable task claims it and never otherwise.

Three states, deliberately, because two would collapse the interesting one:

- **`covered`** — at least one installed task declares this category *and* the
  task can run on this machine.
- **`declared_only`** — a task claims the category but cannot run here (missing
  tooling), so nothing has been measured.
- **`not_covered`** — nothing claims it. Most of the ten are in this state, and
  saying so plainly is the entire value of the table.

The category list is a fixed set of identifiers, and this file does not reproduce
OWASP's text: the identifiers are pointers into a document a reader should read
rather than a paraphrase they should trust.
"""

from __future__ import annotations

from typing import Any

#: The 2026 Agentic Top 10 identifiers, in rank order, with a short label used
#: only for navigation. These are pointers to OWASP's document, not a summary of
#: it -- a paraphrased security control is a control nobody can check against the
#: source.
OWASP_AGENTIC_2026: tuple[tuple[str, str], ...] = (
    ("AAI01", "Prompt injection"),
    ("AAI02", "Sensitive information disclosure"),
    ("AAI03", "Excessive agency"),
    ("AAI04", "Supply chain and tool integrity"),
    ("AAI05", "Insecure tool execution"),
    ("AAI06", "Memory and context poisoning"),
    ("AAI07", "Identity and impersonation"),
    ("AAI08", "Misaligned or deceptive behaviour"),
    ("AAI09", "Unbounded resource consumption"),
    ("AAI10", "Insufficient monitoring and traceability"),
)

COVERED = "covered"
DECLARED_ONLY = "declared_only"
NOT_COVERED = "not_covered"


def _declared_categories(task: Any) -> set[str]:
    """OWASP identifiers a task claims, from its own metadata.

    Read from `metadata.attack.owasp_ids` rather than parsed out of the prose
    `owasp` field: a matrix built by substring-matching free text would report
    coverage that depends on how an author phrased a sentence.
    """
    metadata = getattr(task, "metadata", None) or {}
    attack = metadata.get("attack") if isinstance(metadata, dict) else None
    if not isinstance(attack, dict):
        return set()
    ids = attack.get("owasp_ids")
    if isinstance(ids, list):
        return {str(i).upper() for i in ids}
    return set()


def coverage_matrix(tasks: list[Any] | None = None) -> dict[str, Any]:
    """Which OWASP Agentic categories this installation can actually exercise."""
    from tooltrace.tasks.availability import partition
    from tooltrace.tasks.loader import load_all_tasks

    all_tasks = list(tasks) if tasks is not None else load_all_tasks()
    runnable, skipped = partition(all_tasks)
    runnable_ids = {t.id for t in runnable}
    skip_reasons = {t.id: reason for t, reason in skipped}

    rows: list[dict[str, Any]] = []
    for identifier, label in OWASP_AGENTIC_2026:
        claiming = [t for t in all_tasks if identifier in _declared_categories(t)]
        runnable_here = [t for t in claiming if t.id in runnable_ids]

        if runnable_here:
            status = COVERED
            note = ""
        elif claiming:
            status = DECLARED_ONLY
            note = "; ".join(
                f"{t.id}: {skip_reasons.get(t.id, 'cannot run here')}" for t in claiming
            )
        else:
            status = NOT_COVERED
            note = "no installed task declares this category"

        rows.append(
            {
                "id": identifier,
                "label": label,
                "status": status,
                "tasks": sorted(t.id for t in runnable_here),
                "declared_by": sorted(t.id for t in claiming),
                "note": note,
            }
        )

    covered = [r for r in rows if r["status"] == COVERED]
    return {
        "categories": rows,
        "covered": len(covered),
        "total": len(rows),
        # The number that matters, phrased so it cannot be read as a score. A
        # "70% OWASP coverage" figure would be quoted; this cannot be.
        "statement": (
            f"{len(covered)} of {len(rows)} OWASP Agentic Top 10 categories are exercised by "
            "a task that runs on this machine. The rest are not measured here, which is not "
            "the same as an agent being safe from them."
        ),
        "source": "OWASP Top 10 for Agentic Applications (2026). Identifiers are pointers to "
        "that document, not a summary of it.",
    }


def render_markdown(matrix: dict[str, Any]) -> str:
    """A table for the docs, generated rather than maintained."""
    lines = [
        "| OWASP | Category | Status | Exercised by |",
        "|---|---|---|---|",
    ]
    labels = {
        COVERED: "covered",
        DECLARED_ONLY: "declared, not runnable here",
        NOT_COVERED: "not covered",
    }
    for row in matrix["categories"]:
        tasks = ", ".join(f"`{t}`" for t in row["tasks"]) or "-"
        lines.append(f"| {row['id']} | {row['label']} | {labels[row['status']]} | {tasks} |")
    lines += ["", matrix["statement"], "", f"_{matrix['source']}_"]
    return "\n".join(lines) + "\n"
