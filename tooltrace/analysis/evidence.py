"""Assemble an evidence dossier from bundles, for a regulated review.

The remaining EU AI Act provisions became applicable on 2 August 2026, and the
phrase every compliance guide repeats is that an organisation must
**demonstrate** compliance rather than claim it. A checksummed, tamper-evident,
reproducible `.tooltrace` bundle is already an evidence artifact for exactly
that. What was missing was anything that gathered bundles into the shape a
reviewer reads.

The single most important property of this module is what it refuses to do.

**It does not determine compliance, and it must never say it does.** Compliance
is an organisational determination about a specific system in a specific
deployment context, made by people with accountability for it. This produces
*inputs* to that determination: what was measured, on what, when, by which code,
and — as prominently — **what was not measured**. A tool that emitted a
"compliant" verdict for a benchmark run would be worse than useless in a domain
with €35M penalties; it would be actively misleading, and the fact that a
machine produced it would lend it unearned authority.

So every obligation carries `evidence` *and* `gaps`, the gaps are never empty by
construction, and the dossier states its own limits at the top.

Article references are to the obligations for high-risk systems and are included
so a reviewer can find the relevant text. They are pointers, not legal advice,
and this file is not a legal opinion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tooltrace.artifacts.bundles import load_bundle_result, read_manifest, verify_bundle

#: The obligation set this dossier organises evidence against. Titles are
#: paraphrased for navigation; the Article number is what a reviewer follows.
OBLIGATIONS: tuple[tuple[str, str], ...] = (
    ("Article 9", "Risk management system"),
    ("Article 11", "Technical documentation"),
    ("Article 12", "Record-keeping and automatic logging"),
    ("Article 15", "Accuracy, robustness and cybersecurity"),
)


@dataclass
class ObligationEvidence:
    """What was measured for one obligation, and what was not."""

    article: str
    title: str
    evidence: list[str] = field(default_factory=list)
    #: Never empty by construction. An obligation with no stated gap would read
    #: as fully satisfied, which this tool is not entitled to assert.
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": self.article,
            "title": self.title,
            "evidence": self.evidence,
            "gaps": self.gaps,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unreadable(bundle_dir: Path, problems: list[str]) -> dict[str, Any]:
    """A bundle too damaged to parse is still a fact a reviewer needs.

    Crashing here would drop the one bundle most worth seeing. An audit wants
    the corrupt artifact listed, not the report abandoned.
    """
    return {
        "bundle": bundle_dir.name,
        "verified": False,
        "verification_problems": problems,
        "task_id": "(unreadable)",
        "task_version": "",
        "agent": "(unreadable)",
        "run_id": "",
        "success": False,
        "score": None,
        "failure_reason": None,
        "created_at": "",
        "framework_version": "",
        "compatibility_key": "",
        "trust_state": "",
        "manifest_sha256": "",
    }


def _bundle_facts(bundle_dir: Path) -> dict[str, Any]:
    """Everything a reviewer needs about one run, plus whether it verifies."""
    problems = verify_bundle(bundle_dir)
    try:
        manifest = read_manifest(bundle_dir)
        result = load_bundle_result(bundle_dir)
    except Exception as exc:
        return _unreadable(bundle_dir, [*problems, f"unreadable: {type(exc).__name__}: {exc}"])
    return {
        "bundle": bundle_dir.name,
        "verified": not problems,
        "verification_problems": problems,
        "task_id": result.task_id,
        "task_version": result.task_version,
        "agent": result.agent,
        "run_id": result.run_id,
        "success": result.success,
        "score": result.score.total,
        "failure_reason": result.failure_reason.value if result.failure_reason else None,
        "created_at": str(manifest.get("created_at") or ""),
        "framework_version": str(manifest.get("framework_version") or ""),
        "compatibility_key": str(manifest.get("compatibility_key") or ""),
        "trust_state": str(manifest.get("trust_state") or ""),
        "manifest_sha256": _sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")),
    }


def _security_runs(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in facts if str(f["task_id"]).startswith("security/")]


def build_obligations(facts: list[dict[str, Any]]) -> list[ObligationEvidence]:
    """Map what these runs actually measured onto the obligation set."""
    verified = [f for f in facts if f["verified"]]
    unverified = [f for f in facts if not f["verified"]]
    tasks = sorted({f["task_id"] for f in facts})
    agents = sorted({f["agent"] for f in facts})
    security = _security_runs(facts)
    failures = [f for f in facts if not f["success"]]

    risk = ObligationEvidence(*OBLIGATIONS[0])
    risk.evidence.append(f"{len(facts)} recorded run(s) across {len(tasks)} task(s)")
    if failures:
        reasons = sorted({str(f["failure_reason"]) for f in failures if f["failure_reason"]})
        risk.evidence.append(f"{len(failures)} failed run(s), classified as: {reasons}")
    risk.gaps.append(
        "A benchmark exercises the failure modes its task packs encode. It is not a "
        "hazard analysis of your deployment, and does not enumerate risks specific to it."
    )
    if not security:
        risk.gaps.append("No adversarial (security/) runs are included in this dossier.")

    documentation = ObligationEvidence(*OBLIGATIONS[1])
    documentation.evidence.append(f"Task definitions and versions recorded per run: {tasks}")
    documentation.evidence.append(f"Agent(s) under test: {agents}")
    versions = sorted({f["framework_version"] for f in facts if f["framework_version"]})
    documentation.evidence.append(f"Harness version(s) recorded in every manifest: {versions}")
    documentation.gaps.append(
        "This documents the evaluation, not the system. Intended purpose, design "
        "choices, training data and human-oversight measures are outside what a "
        "benchmark run can evidence."
    )

    logging = ObligationEvidence(*OBLIGATIONS[2])
    logging.evidence.append(
        f"{len(verified)} of {len(facts)} bundle(s) verify against their SHA-256 manifests"
    )
    logging.evidence.append(
        "Each bundle carries the full event trace, the exact task definition, the "
        "workspace diff, per-assertion scoring and host environment metadata"
    )
    if unverified:
        logging.gaps.append(
            f"{len(unverified)} bundle(s) failed verification and are listed as such: "
            f"{[f['bundle'] for f in unverified]}"
        )
    logging.gaps.append(
        "Checksums are tamper-evident, not tamper-proof: they detect modification "
        "of a bundle, and do not by themselves establish who produced it. Signing "
        "is available separately via cosign."
    )

    accuracy = ObligationEvidence(*OBLIGATIONS[3])
    if facts:
        rate = sum(1 for f in facts if f["success"]) / len(facts)
        accuracy.evidence.append(f"Measured success rate {rate:.3f} over {len(facts)} run(s)")
    if security:
        resisted = sum(1 for f in security if f["success"])
        accuracy.evidence.append(
            f"Adversarial: {resisted} of {len(security)} injection attempt(s) resisted"
        )
    else:
        accuracy.gaps.append(
            "Cybersecurity evidence is absent: no security/ tasks were run. Include "
            "them to evidence robustness against prompt injection."
        )
    if len(facts) < 30:
        accuracy.gaps.append(
            f"Sample size is {len(facts)}. A rate from fewer than 30 runs has a wide "
            "confidence interval and should not be presented as a stable measurement."
        )
    accuracy.gaps.append(
        "Accuracy is measured against this project's deterministic assertions, on "
        "these task packs. It does not generalise to inputs the packs do not cover."
    )

    return [risk, documentation, logging, accuracy]


def build_dossier(bundle_dirs: list[Path], *, generated_at: str) -> dict[str, Any]:
    """The dossier: facts, obligation mapping, and a hash chain over both.

    `generated_at` is injected rather than read from the clock so the output is
    reproducible and a caller can date it deliberately.
    """
    facts = [_bundle_facts(b) for b in sorted(bundle_dirs)]
    obligations = [o.to_dict() for o in build_obligations(facts)]

    # A hash chain over the run facts in order: each entry commits to the one
    # before it, so a removed or reordered run is detectable, not just a
    # modified one.
    chain: list[dict[str, str]] = []
    previous = "0" * 64
    for fact in facts:
        digest = _sha256((previous + json.dumps(fact, sort_keys=True)).encode("utf-8"))
        chain.append({"bundle": str(fact["bundle"]), "previous": previous, "entry": digest})
        previous = digest

    return {
        "schema": "tooltrace-evidence/1",
        "generated_at": generated_at,
        "statement": (
            "This dossier is evidence, not a compliance determination. It records what "
            "was measured, on what, when, and by which version of the harness, together "
            "with what was not measured. Whether an AI system meets its legal "
            "obligations is an organisational determination about that system in its "
            "deployment context, made by people accountable for it. Nothing here "
            "substitutes for that."
        ),
        "runs": facts,
        "obligations": obligations,
        "hash_chain": chain,
        "chain_head": previous,
    }


def verify_chain(dossier: dict[str, Any]) -> list[str]:
    """Recompute the hash chain; report any run that was altered or removed."""
    problems: list[str] = []
    previous = "0" * 64
    runs = dossier.get("runs") or []
    chain = dossier.get("hash_chain") or []
    if len(runs) != len(chain):
        problems.append(f"chain covers {len(chain)} runs but the dossier lists {len(runs)}")
        return problems
    for fact, entry in zip(runs, chain, strict=True):
        expected = _sha256((previous + json.dumps(fact, sort_keys=True)).encode("utf-8"))
        if entry.get("entry") != expected:
            problems.append(f"chain broken at {fact.get('bundle')}: run data was altered")
            return problems
        previous = expected
    if dossier.get("chain_head") != previous:
        problems.append("chain head does not match the recomputed chain")
    return problems


def render_markdown(dossier: dict[str, Any]) -> str:
    """A reviewer-readable rendering. Gaps are given equal prominence."""
    lines = [
        "# Evidence dossier",
        "",
        f"Generated {dossier['generated_at']} · chain head `{dossier['chain_head'][:16]}…`",
        "",
        "> **This is evidence, not a compliance determination.**",
        "> " + dossier["statement"],
        "",
        "## Runs",
        "",
        "| Bundle | Task | Agent | Verified | Success | Score |",
        "|---|---|---|---|---|---|",
    ]
    for run in dossier["runs"]:
        lines.append(
            f"| `{run['bundle']}` | {run['task_id']}@{run['task_version']} | {run['agent']} "
            f"| {'yes' if run['verified'] else '**NO**'} | {'yes' if run['success'] else 'no'} "
            f"| {run['score']} |"
        )

    lines += ["", "## Obligations", ""]
    for obligation in dossier["obligations"]:
        lines.append(f"### {obligation['article']} — {obligation['title']}")
        lines.append("")
        lines.append("**Evidence in this dossier**")
        lines += [f"- {item}" for item in obligation["evidence"]] or ["- (none)"]
        lines.append("")
        lines.append("**Not evidenced here**")
        lines += [f"- {item}" for item in obligation["gaps"]]
        lines.append("")
    return "\n".join(lines) + "\n"
