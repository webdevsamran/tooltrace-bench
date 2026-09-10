"""The same evidence, mapped onto NIST AI RMF and ISO/IEC 42001.

`evidence.py` organises what a set of runs measured against the EU AI Act's
obligations for high-risk systems. Two other control sets get asked for by the
same reviewers, and the facts do not change -- only the vocabulary. So this reads
the identical bundle facts and re-files them, rather than re-deriving anything.

**The reason this module is mostly refusals.** Both frameworks are far larger
than anything a benchmark can speak to, and a mapping that quietly listed only
the controls it could evidence would imply coverage of the rest:

- **NIST AI RMF** is organised around four functions. GOVERN is entirely
  organisational -- policies, accountability, culture -- and a test harness
  cannot evidence a single one of its categories. MAP is about context and
  intended use, which is a property of your deployment and not of a run. MEASURE
  is where a benchmark lives, and even there it covers some categories and not
  others. MANAGE is about what you *do* with a finding.
- **ISO/IEC 42001** is a *management system* standard. Clauses 4-10 are about
  leadership, planning, competence and continual improvement; Annex A is the
  control set, and a benchmark touches a handful of it.

So every framework here reports three sets: controls with evidence, controls
this project could evidence and these runs did not, and controls **no benchmark
can evidence**. The third is the one that matters, and it is never empty.

Nothing here is legal advice or a certification. Control titles are paraphrased
for navigation; the identifier is what a reviewer follows into the actual text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: What a control can be, from this tool's point of view.
EVIDENCED = "evidenced"
NOT_RUN = "not_run"
OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class Control:
    """One control, and whether a benchmark could ever say anything about it."""

    id: str
    title: str
    #: When False, no run of anything could evidence this control. Recorded on
    #: the control rather than decided at report time, so the claim is auditable
    #: as data instead of buried in a branch.
    benchmark_can_evidence: bool
    #: Why, in the caller's terms. On an out-of-scope control this is the whole
    #: value of the row.
    note: str


@dataclass(frozen=True)
class Framework:
    id: str
    name: str
    #: The revision these identifiers come from. A mapping to an undated
    #: framework is a mapping nobody can check.
    revision: str
    #: What kind of thing the framework is, because it changes what a mapping
    #: means. A management-system standard and a risk framework are not the
    #: same claim.
    kind: str
    controls: tuple[Control, ...]
    caveat: str


NIST_AI_RMF = Framework(
    id="nist-ai-rmf",
    name="NIST AI Risk Management Framework",
    revision="1.0 (AI 100-1, January 2023)",
    kind="voluntary risk-management framework",
    caveat=(
        "The AI RMF is voluntary and outcome-based; it defines no certification and "
        "no pass mark. GOVERN is organisational in its entirety and MAP is about your "
        "deployment context, so a test harness can evidence part of MEASURE and "
        "contribute inputs to MANAGE. A mapping that listed only the categories it "
        "could reach would imply the rest."
    ),
    controls=(
        Control(
            "GOVERN-1",
            "Policies, processes and procedures for AI risk",
            False,
            "An organisational function. No run of any harness evidences a policy.",
        ),
        Control(
            "GOVERN-4",
            "Culture of risk identification and escalation",
            False,
            "About people and incentives. Outside anything a benchmark observes.",
        ),
        Control(
            "MAP-1",
            "Context, intended purpose and deployment setting established",
            False,
            "A property of your system in your context, not of a task pack.",
        ),
        Control(
            "MAP-5",
            "Impacts to individuals, groups and society characterised",
            False,
            "Requires knowing who the system affects. A benchmark does not.",
        ),
        Control(
            "MEASURE-1",
            "Appropriate methods and metrics identified and applied",
            True,
            "Deterministic assertions, confidence intervals and a stated sample size.",
        ),
        Control(
            "MEASURE-2",
            "Systems evaluated for trustworthy characteristics",
            True,
            "Success rate, robustness under fault injection, and security resistance.",
        ),
        Control(
            "MEASURE-2.7",
            "Security and resilience examined",
            True,
            "The security task packs, scored per attack class with Wilson intervals.",
        ),
        Control(
            "MEASURE-3",
            "Mechanisms for tracking identified risks over time",
            True,
            "Baselines, the drift report, and dated bundles that can be re-compared.",
        ),
        Control(
            "MEASURE-4",
            "Feedback about efficacy gathered from domain experts and users",
            False,
            "Human feedback is not something an automated run produces.",
        ),
        Control(
            "MANAGE-2",
            "Strategies to maximise benefit and minimise negative impact",
            False,
            "A decision about what to do with a finding, not the finding itself.",
        ),
        Control(
            "MANAGE-4",
            "Post-deployment monitoring plans in place",
            True,
            "Partially: the drift and SLO machinery is the measurement half of a "
            "monitoring plan. The plan itself is yours.",
        ),
    ),
)


ISO_42001 = Framework(
    id="iso-42001",
    name="ISO/IEC 42001 AI management system",
    revision="2023",
    kind="management-system standard (certifiable)",
    caveat=(
        "ISO/IEC 42001 certifies a *management system*, not a model or a run. Clauses "
        "4-10 -- context, leadership, planning, support, operation, evaluation, "
        "improvement -- are organisational and no evaluation output speaks to them. "
        "What a harness contributes is evidence for a few Annex A controls, which an "
        "auditor reads alongside everything else. This is not a certification and "
        "cannot be presented as progress toward one."
    ),
    controls=(
        Control(
            "Clause 5",
            "Leadership and commitment",
            False,
            "Organisational. A run cannot evidence leadership.",
        ),
        Control(
            "Clause 7.2",
            "Competence of people working on the AI system",
            False,
            "About people. Nothing in a bundle is about people.",
        ),
        Control(
            "A.6.2.4",
            "AI system verification and validation",
            True,
            "The core of what this project produces: deterministic verification "
            "against declared assertions, with reproducible artifacts.",
        ),
        Control(
            "A.6.2.6",
            "AI system operation and monitoring",
            True,
            "Partially: drift detection and error budgets over recorded windows.",
        ),
        Control(
            "A.6.2.8",
            "AI system recording of event logs",
            True,
            "Every run carries a full, checksummed event trace and workspace diff.",
        ),
        Control(
            "A.4.6",
            "AI system impact assessment",
            False,
            "Requires the deployment context and the affected people.",
        ),
        Control(
            "A.7.4",
            "Quality of data for AI systems",
            False,
            "About training and operational data, which a harness never sees.",
        ),
        Control(
            "A.9.3",
            "Objectives for responsible use of the AI system",
            False,
            "An organisational statement of intent.",
        ),
        Control(
            "A.10.2",
            "Allocating responsibilities within the AI supply chain",
            True,
            "Partially: the attestation trust ladder records who reproduced a "
            "result and on which machine. It does not allocate responsibility.",
        ),
    ),
)


FRAMEWORKS: dict[str, Framework] = {f.id: f for f in (NIST_AI_RMF, ISO_42001)}


def _evidence_for(control: Control, facts: list[dict[str, Any]]) -> list[str]:
    """What these runs offer for one control, drawn from the same facts as the dossier."""
    if not control.benchmark_can_evidence:
        return []
    total = len(facts)
    verified = sum(1 for f in facts if f.get("verified"))
    security = [f for f in facts if str(f.get("task_id", "")).startswith("security/")]
    successes = sum(1 for f in facts if f.get("success"))
    tasks = sorted({str(f.get("task_id")) for f in facts})

    if control.id.startswith(("MEASURE-2.7",)):
        if not security:
            return []
        resisted = sum(1 for f in security if f.get("success"))
        return [f"{resisted} of {len(security)} adversarial run(s) resisted the attack"]
    if control.id in {"MEASURE-1", "MEASURE-2", "A.6.2.4"}:
        if not total:
            return []
        return [
            f"{total} run(s) over {len(tasks)} task(s), {successes} successful",
            "Every assertion is deterministic and recorded per run with its weight",
        ]
    if control.id in {"MEASURE-3", "MANAGE-4", "A.6.2.6"}:
        if not total:
            return []
        return [
            f"{total} dated run(s) recorded as re-comparable bundles",
            "Drift and error-budget reporting operates over windows of these runs",
        ]
    if control.id == "A.6.2.8":
        if not total:
            return []
        return [
            f"{verified} of {total} bundle(s) verify against their SHA-256 manifests",
            "Each carries the full event trace, task definition and workspace diff",
        ]
    if control.id == "A.10.2":
        states = sorted({str(f.get("trust_state")) for f in facts if f.get("trust_state")})
        return [f"Trust states recorded across these runs: {states}"] if states else []
    return []


@dataclass
class ControlEvidence:
    control: Control
    state: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.control.id,
            "title": self.control.title,
            "state": self.state,
            "note": self.control.note,
            "evidence": self.evidence,
        }


def map_controls(framework_id: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    """File a set of run facts against one framework's controls.

    Three states, and the third is the point. `out_of_scope` means no run of any
    harness could evidence the control -- reporting it alongside the others is
    what stops a partial mapping from reading as a complete one.
    """
    if framework_id not in FRAMEWORKS:
        raise ValueError(
            f"unknown framework {framework_id!r}; expected one of {', '.join(sorted(FRAMEWORKS))}"
        )
    framework = FRAMEWORKS[framework_id]

    rows: list[ControlEvidence] = []
    for control in framework.controls:
        if not control.benchmark_can_evidence:
            rows.append(ControlEvidence(control, OUT_OF_SCOPE))
            continue
        found = _evidence_for(control, facts)
        rows.append(ControlEvidence(control, EVIDENCED if found else NOT_RUN, found))

    evidenced = [r for r in rows if r.state == EVIDENCED]
    not_run = [r for r in rows if r.state == NOT_RUN]
    out_of_scope = [r for r in rows if r.state == OUT_OF_SCOPE]

    return {
        "framework": framework.id,
        "name": framework.name,
        "revision": framework.revision,
        "kind": framework.kind,
        "caveat": framework.caveat,
        "controls": [r.to_dict() for r in rows],
        "counts": {
            "evidenced": len(evidenced),
            "not_run": len(not_run),
            "out_of_scope": len(out_of_scope),
            "total_listed": len(rows),
        },
        "statement": (
            f"{len(evidenced)} of {len(rows)} listed controls have evidence from these runs. "
            f"{len(not_run)} could be evidenced and were not. "
            f"**{len(out_of_scope)} cannot be evidenced by any benchmark** and are listed so "
            "this mapping is not read as coverage. The controls listed here are a subset of "
            f"{framework.name} chosen for relevance; the framework is larger than this table."
        ),
    }


def render_markdown(mapping: dict[str, Any]) -> str:
    """A table a reviewer can read, with the out-of-scope rows kept in."""
    lines = [
        f"## {mapping['name']} ({mapping['revision']})",
        "",
        f"*{mapping['kind']}.* {mapping['caveat']}",
        "",
        "| Control | State | Evidence or reason |",
        "|---|---|---|",
    ]
    for row in mapping["controls"]:
        detail = "; ".join(row["evidence"]) if row["evidence"] else row["note"]
        lines.append(f"| `{row['id']}` {row['title']} | {row['state']} | {detail} |")
    lines += ["", mapping["statement"], ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Regulatory changelog: when each evidence capability arrived
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseEvidence:
    """What a release changed about what this project can evidence.

    Not what the release *did* -- that is the changelog. This is the narrower
    question a reviewer asks: from which version could a dossier assembled with
    this tool speak to a given obligation at all?
    """

    version: str
    date: str
    #: Control and obligation identifiers this release made evidenceable for
    #: the first time. Empty is legitimate and common: most releases improve
    #: something that was already evidenceable.
    first_evidenced: tuple[str, ...]
    summary: str


#: Machine-checked against `CHANGELOG.md` by
#: `tests/test_regulatory_changelog.py`: every version here must have a heading
#: there, and every released version there must appear here. A regulatory
#: changelog that drifts from the real one is worse than none, because it is the
#: document a reviewer would trust.
RELEASE_EVIDENCE: tuple[ReleaseEvidence, ...] = (
    ReleaseEvidence(
        version="0.1.0",
        date="unreleased-date-not-recorded",
        first_evidenced=("Article 12", "A.6.2.8"),
        summary=(
            "Checksummed `.tooltrace` bundles with full event traces. Record-keeping "
            "became evidenceable; nothing else did"
        ),
    ),
    ReleaseEvidence(
        version="0.2.0",
        date="2026-08-23",
        first_evidenced=("Article 11", "MEASURE-1"),
        summary=(
            "Task protocol v2 with provenance manifests, versioned packs and declared "
            "scoring contracts. What was run became documentable, not just recorded"
        ),
    ),
    ReleaseEvidence(
        version="0.2.1",
        date="2026-08-26",
        first_evidenced=(),
        summary=(
            "Structural pass. No new evidence capability, and saying so is the point: "
            "most releases do not add one"
        ),
    ),
    ReleaseEvidence(
        version="0.3.0",
        date="2026-09-07",
        first_evidenced=("MEASURE-3", "A.6.2.6"),
        summary=(
            "Baselines, trends and comparison across dated runs, so tracking a measured "
            "property over time became possible"
        ),
    ),
    ReleaseEvidence(
        version="Unreleased",
        date="",
        first_evidenced=(
            "Article 9",
            "Article 15",
            "MEASURE-2",
            "MEASURE-2.7",
            "MANAGE-4",
            "A.6.2.4",
            "A.10.2",
        ),
        summary=(
            "The security packs, the evidence dossier, drift detection and the "
            "attestation trust ladder. This is where most of the mapping became "
            "answerable at all"
        ),
    ),
)


def regulatory_changelog() -> dict[str, Any]:
    """When each obligation first became evidenceable, newest release last.

    The question this answers is narrower than "what changed": a reviewer
    holding a dossier wants to know from which version the tool could speak to
    an obligation at all, because a dossier produced before that release is
    silent on it for a reason that is not the agent's.
    """
    rows = [
        {
            "version": entry.version,
            "date": entry.date,
            "first_evidenced": list(entry.first_evidenced),
            "summary": entry.summary,
        }
        for entry in RELEASE_EVIDENCE
    ]
    covered: list[str] = []
    for entry in RELEASE_EVIDENCE:
        covered.extend(entry.first_evidenced)

    return {
        "releases": rows,
        "evidenceable_now": sorted(set(covered)),
        "statement": (
            f"{len(set(covered))} obligation or control identifier(s) became evidenceable "
            f"across {len(rows)} release(s). A release adding none is listed too: most "
            "releases improve something already evidenceable, and hiding those would make "
            "the list read as steady regulatory progress rather than as a record."
        ),
        "caveat": (
            "Becoming *able to evidence* an obligation is not satisfying it. This records "
            "when the tool grew a capability, not whether any particular system complies."
        ),
    }
