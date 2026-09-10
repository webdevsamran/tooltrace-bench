"""What a bundle had removed, what shapes remain, and what nobody can certify.

Sharing a trace means sharing whatever the agent read and wrote. `sanitize.py`
already strips secret-shaped strings on the way in, but "we ran a redactor" is
not a statement anyone can act on before publishing a bundle. This produces the
statement: which classes were found and removed, which PII-shaped patterns are
still present, and — at the same prominence — what a scan of this kind cannot
establish.

## Two refusals, and they are the point

**A clean scan is not proof of absence.** Every detector here matches a *shape*.
An email address has a shape. A phone number has a shape. A person's name does
not; neither does "the patient mentioned she had been drinking again", and
neither does a medical record number that happens to look like an order id. A
report that said "no PII found" would be read as "safe to publish", and it would
be wrong in exactly the cases that matter most.

**This is not differential privacy, and it cannot be.** DP means adding
calibrated noise under an epsilon budget. A `.tooltrace` bundle's entire value is
that a third party can reproduce it byte for byte and get the same checksums;
noise would break the reproduction the bundle exists to support. The two
properties are in direct conflict, so this project does redaction and says so,
rather than borrowing a word that would imply a guarantee it does not provide.

What is left is still useful: a dated, reviewable record of what was removed and
what patterns survive, produced before a bundle is shared rather than after
somebody notices.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tooltrace.security.sanitize import _PATTERNS as SECRET_PATTERNS
from tooltrace.security.sanitize import _REDACTED, find_secrets

#: Personal-data shapes, deliberately separate from the secret patterns.
#: A secret is redacted on the way in; these are *reported*, because removing
#: them automatically would silently change a trace whose value is being an
#: exact record. The decision to redact an email address belongs to whoever is
#: publishing, not to the harness.
PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "email-address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "Directly identifying, and the most common thing to leak into a trace",
    ),
    (
        "ipv4-address",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "Personal data under GDPR when it identifies a subscriber; often also a version string",
    ),
    (
        "phone-number",
        re.compile(r"(?<![\d.])(?:\+\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?)?\d{3,4}[ -]\d{3,4}\b"),
        "High false-positive rate: a date range or a part number matches this shape",
    ),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
        "Financial identifier",
    ),
    (
        "credit-card-like",
        re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
        "Shape only; no Luhn check, so an order number of this length matches",
    ),
    (
        "us-ssn-like",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "Shape only; a product code in the same format matches",
    ),
    (
        "date-of-birth-like",
        re.compile(r"(?i)\b(?:dob|date of birth)\b\s*[:=]?\s*\d"),
        "Labelled rather than inferred, because a bare date is not a birth date",
    ),
)

#: Categories of personal data that have **no detectable shape**. Listed by name
#: in every report: a reader who sees six patterns checked and no warning will
#: assume the six are the whole problem.
UNDETECTABLE: tuple[str, ...] = (
    "personal names, which look like any other words",
    "free-text disclosures about a person, which have no format at all",
    "internal identifiers that identify someone only when joined to another system",
    "photographs, audio and anything else that is not text",
    "location described in prose rather than as coordinates",
)

#: Files inside a bundle that can carry text an agent saw or produced.
SCANNED_FILES: tuple[str, ...] = (
    "trace.jsonl",
    "task.yaml",
    "workspace.diff",
    "result.json",
    "scoring.json",
)


@dataclass(frozen=True)
class Finding:
    label: str
    count: int
    #: Where it was seen, by file. Never the matched text: a report that
    #: quoted the personal data it found would be the disclosure.
    files: tuple[str, ...]
    note: str


def _scan_text(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, pattern, _note in PII_PATTERNS:
        found = len(pattern.findall(text))
        if found:
            counts[label] = found
    return counts


def _bundle_text(bundle_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for name in SCANNED_FILES:
        path = bundle_dir / name
        if path.is_file():
            texts[name] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def redaction_report(bundle_dir: Path) -> dict[str, Any]:
    """What this bundle had removed, what shapes remain, and what is unknowable."""
    texts = _bundle_text(bundle_dir)
    if not texts:
        return {
            "bundle": bundle_dir.name,
            "readable": False,
            "reason": f"no readable files under {bundle_dir}",
        }

    per_label: dict[str, dict[str, Any]] = {}
    for filename, text in texts.items():
        for label, count in _scan_text(text).items():
            entry = per_label.setdefault(label, {"count": 0, "files": []})
            entry["count"] += count
            entry["files"].append(filename)

    notes = {label: note for label, _pattern, note in PII_PATTERNS}
    findings = [
        Finding(
            label=label,
            count=int(entry["count"]),
            files=tuple(sorted(set(entry["files"]))),
            note=notes[label],
        )
        for label, entry in sorted(per_label.items())
    ]

    # Evidence that the sanitiser ran, taken from the artifact rather than
    # assumed: the marker is what it leaves behind.
    redaction_markers = sum(text.count(_REDACTED) for text in texts.values())
    # And a check that it did not miss anything it claims to catch. A secret
    # pattern still matching after sanitisation is a defect in the sanitiser,
    # not a finding about the run.
    residual_secrets = sorted({f.label for text in texts.values() for f in find_secrets(text)})

    return {
        "bundle": bundle_dir.name,
        "readable": True,
        "files_scanned": sorted(texts),
        "redaction_markers": redaction_markers,
        "secret_classes_checked": len(SECRET_PATTERNS),
        "residual_secret_classes": residual_secrets,
        "pii_findings": [
            {"label": f.label, "count": f.count, "files": list(f.files), "note": f.note}
            for f in findings
        ],
        "undetectable": list(UNDETECTABLE),
        # A determination, not a certification, and named so.
        "safe_to_publish": None,
        "statement": _statement(findings, redaction_markers, residual_secrets),
        "not_differential_privacy": (
            "This is redaction, not differential privacy. DP means calibrated noise under "
            "an epsilon budget; a bundle's value is that a third party can reproduce it "
            "byte for byte, and noise would break the reproduction it exists to support. "
            "The two properties are in direct conflict, so this project does not claim DP."
        ),
        "limit": (
            "A clean scan is not proof of absence. Every detector here matches a shape, "
            "and the most sensitive categories have none: a person's name looks like any "
            "other word. Whether this bundle can be published is a human decision."
        ),
    }


def _statement(findings: list[Finding], markers: int, residual: list[str]) -> str:
    parts: list[str] = []
    if markers:
        parts.append(f"{markers} value(s) were redacted on capture")
    else:
        parts.append("nothing matched a secret pattern on capture")
    if residual:
        parts.append(
            f"**{len(residual)} secret class(es) still match after sanitisation "
            f"({', '.join(residual)}), which is a defect in the sanitiser rather than "
            "a property of the run**"
        )
    if findings:
        total = sum(f.count for f in findings)
        parts.append(
            f"{total} personal-data-shaped match(es) across "
            f"{len(findings)} class(es): {', '.join(f.label for f in findings)}"
        )
    else:
        parts.append("no personal-data shape matched, which is not the same as none present")
    return "; ".join(parts) + "."


def certificate(bundle_dirs: list[Path], *, generated_at: str) -> dict[str, Any]:
    """A dated record across bundles, for attaching to a share decision.

    Called a record rather than a certificate in everything it outputs. The
    function name is the word people search for; the content refuses the claim
    the word implies.
    """
    reports = [redaction_report(b) for b in sorted(bundle_dirs)]
    readable = [r for r in reports if r.get("readable")]
    with_findings = [r for r in readable if r["pii_findings"]]
    with_residual = [r for r in readable if r["residual_secret_classes"]]

    return {
        "schema": "tooltrace-redaction/1",
        "generated_at": generated_at,
        "bundles": reports,
        "counts": {
            "scanned": len(readable),
            "unreadable": len(reports) - len(readable),
            "with_pii_shapes": len(with_findings),
            "with_residual_secrets": len(with_residual),
        },
        "is_certification": False,
        "statement": (
            f"{len(readable)} bundle(s) scanned. {len(with_findings)} contain at least one "
            "personal-data shape. "
            + (
                f"{len(with_residual)} still match a secret pattern after sanitisation, "
                "which is a defect to fix before sharing anything. "
                if with_residual
                else ""
            )
            + "This is a record of what a shape-based scan found, not a certification "
            "that a bundle is safe to publish. That decision is a human one, and the "
            "categories most worth worrying about have no shape to scan for."
        ),
        "undetectable": list(UNDETECTABLE),
    }


def render_markdown(record: dict[str, Any]) -> str:
    lines = [
        "# Redaction record",
        "",
        f"Generated {record['generated_at']}. **This is not a certification.**",
        "",
        record["statement"],
        "",
        "| Bundle | Redacted on capture | PII shapes found | Residual secrets |",
        "|---|---|---|---|",
    ]
    for report in record["bundles"]:
        if not report.get("readable"):
            lines.append(f"| `{report['bundle']}` | — | unreadable | — |")
            continue
        shapes = ", ".join(f"{f['label']} x {f['count']}" for f in report["pii_findings"]) or "none"
        residual = ", ".join(report["residual_secret_classes"]) or "none"
        lines.append(
            f"| `{report['bundle']}` | {report['redaction_markers']} | {shapes} | {residual} |"
        )
    lines += [
        "",
        "## What this scan cannot see",
        "",
        *[f"- {item}" for item in record["undetectable"]],
        "",
        "A clean row above means no *shape* matched. It does not mean the bundle is "
        "free of personal data, and it is not permission to publish.",
        "",
    ]
    return "\n".join(lines)


def write_record(record: dict[str, Any], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "redaction.json"
    md_path = out_dir / "redaction.md"
    json_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(record), encoding="utf-8")
    return [json_path, md_path]
