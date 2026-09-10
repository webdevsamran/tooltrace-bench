"""Reproduction attestations: what makes the trust ladder mean anything.

`TrustState` declares four levels — `LOCAL`, `COMMUNITY_VALIDATED`,
`REPRODUCED`, `MAINTAINER_VERIFIED` — with a docstring promising they are "never
implied without evidence". Every bundle this project has ever written is `LOCAL`,
and `promote_trust` has no caller outside the test suite. The ladder is a set of
labels nothing can produce, which is worse than three levels honestly held: a
reader seeing four states reasonably assumes some bundle somewhere is in one of
the upper three.

An attestation is the missing evidence. It records that a named party re-ran a
specific bundle and got a specific outcome, in a form a third party can check.

Three rules, and the first is the one that carries the feature:

1. **Self-attestation is not reproduction.** A bundle re-run on the machine that
   produced it demonstrates that the machine is deterministic, which is a
   different and much weaker claim. `REPRODUCED` requires an attestation whose
   hardware profile differs from the original run's, and an attestation that
   fails that test says so rather than being rejected silently — a same-machine
   re-run is still useful evidence, it just is not *this* evidence.

2. **An attestation is bound to one bundle.** It carries the manifest digest, so
   moving it to a different bundle invalidates it. An attestation that could be
   copied between bundles would be a sticker, not evidence.

3. **Unsigned is a claim, not proof.** An attestation with no signature records
   who *says* they reproduced something. That is genuinely useful — it is how
   most reproduction in practice works — and it is not the same as proof, so the
   record carries `signed: false` and every rendering states it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tooltrace.core.models import TrustState

SCHEMA = "tooltrace-attestation/1"

#: What an attestation must contain before it can promote anything.
REQUIRED_FIELDS = (
    "schema",
    "bundle",
    "manifest_sha256",
    "attester",
    "attested_at",
    "outcome",
    "hardware_profile",
)

SAME_MACHINE = "same_machine"
DIFFERENT_MACHINE = "different_machine"
UNKNOWN_MACHINE = "unknown_machine"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_digest(bundle_dir: Path) -> str:
    """A stable digest of the bundle's manifest, used to bind an attestation.

    Over the canonical JSON rather than the file bytes, so reformatting the
    manifest does not silently invalidate every attestation about it.
    """
    from tooltrace.artifacts.bundles import read_manifest

    return _sha256(json.dumps(read_manifest(bundle_dir), sort_keys=True).encode("utf-8"))


def _profile_of(bundle_dir: Path) -> dict[str, Any]:
    from tooltrace.telemetry.hardware import hardware_profile

    path = bundle_dir / "environment.json"
    if not path.is_file():
        return {}
    try:
        return hardware_profile(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def build_attestation(
    bundle_dir: Path,
    *,
    attester: str,
    attested_at: str,
    reproduced: bool,
    detail: str = "",
    hardware: dict[str, Any] | None = None,
    signature: str = "",
) -> dict[str, Any]:
    """Record that `attester` re-ran this bundle and what happened.

    `attested_at` is injected rather than read from the clock, for the same
    reason the evidence dossier injects it: a record that changes every time it
    is generated cannot be compared with a copy someone else holds.
    """
    from tooltrace.runners.runner import environment_metadata
    from tooltrace.telemetry.hardware import hardware_profile

    # Built from `environment_metadata()`, the same function that writes a
    # bundle's `environment.json`. An earlier version assembled the profile by
    # hand with empty `os` and `machine` fields, so every attestation differed
    # from every bundle and a same-machine re-run was reported as independent
    # reproduction -- inverting the one rule this whole module exists to enforce.
    profile = hardware or hardware_profile(environment_metadata(None))
    return {
        "schema": SCHEMA,
        "bundle": bundle_dir.name,
        # Binds the attestation to this bundle. Moving it elsewhere breaks it,
        # which is what stops an attestation being a sticker.
        "manifest_sha256": manifest_digest(bundle_dir),
        "attester": attester,
        "attested_at": attested_at,
        "outcome": "reproduced" if reproduced else "did_not_reproduce",
        "detail": detail,
        "hardware_profile": profile,
        "signature": signature,
        # An unsigned attestation records who *says* they reproduced something.
        # That is how most reproduction actually works, and it is not proof.
        "signed": bool(signature),
    }


def machine_relation(bundle_dir: Path, attestation: dict[str, Any]) -> str:
    """Was this attested on the machine that produced the bundle, or another?

    The distinction the whole feature rests on. A same-machine re-run
    demonstrates that the machine is deterministic; independent reproduction is a
    different and much stronger claim, and conflating them would make
    `REPRODUCED` mean nothing.
    """
    original = _profile_of(bundle_dir)
    attested = attestation.get("hardware_profile") or {}
    if not original or not attested:
        # Neither "same" nor "different" -- the record does not say, and guessing
        # in either direction would be a claim the data does not support.
        return UNKNOWN_MACHINE
    return SAME_MACHINE if original == attested else DIFFERENT_MACHINE


def verify_attestation(bundle_dir: Path, attestation: dict[str, Any]) -> list[str]:
    """Problems with this attestation, as a list. Empty means internally sound.

    "Internally sound" is not "true": an unsigned attestation that verifies here
    is a well-formed claim by whoever wrote it.
    """
    problems: list[str] = []

    for field in REQUIRED_FIELDS:
        if not attestation.get(field):
            problems.append(f"missing required field: {field}")
    if problems:
        return problems

    if attestation.get("schema") != SCHEMA:
        problems.append(f"unknown schema {attestation.get('schema')!r}")
    if attestation.get("bundle") != bundle_dir.name:
        problems.append(
            f"attestation names bundle {attestation.get('bundle')!r}, not {bundle_dir.name!r}"
        )
    try:
        expected = manifest_digest(bundle_dir)
    except Exception as exc:
        problems.append(f"cannot read this bundle's manifest: {type(exc).__name__}: {exc}")
        return problems

    if attestation.get("manifest_sha256") != expected:
        problems.append(
            "manifest digest does not match: this attestation was made about a different "
            "version of this bundle, or a different bundle entirely"
        )
    if attestation.get("outcome") not in {"reproduced", "did_not_reproduce"}:
        problems.append(f"unknown outcome {attestation.get('outcome')!r}")
    return problems


def promotion_for(bundle_dir: Path, attestations: list[dict[str, Any]]) -> dict[str, Any]:
    """The highest trust state these attestations support, and why.

    Deliberately conservative at every step, because the cost of over-promotion
    is that the ladder stops meaning anything, and the cost of under-promotion is
    that someone has to attest again.
    """
    sound = []
    rejected = []
    for attestation in attestations:
        problems = verify_attestation(bundle_dir, attestation)
        if problems:
            rejected.append({"attester": attestation.get("attester"), "problems": problems})
        else:
            sound.append(attestation)

    reproducing = [a for a in sound if a.get("outcome") == "reproduced"]
    independent = [a for a in reproducing if machine_relation(bundle_dir, a) == DIFFERENT_MACHINE]
    same_machine = [a for a in reproducing if machine_relation(bundle_dir, a) == SAME_MACHINE]
    unknown_machine = [a for a in reproducing if machine_relation(bundle_dir, a) == UNKNOWN_MACHINE]
    signed_independent = [a for a in independent if a.get("signed")]

    if signed_independent:
        state = TrustState.REPRODUCED
        reason = (
            f"{len(signed_independent)} signed attestation(s) from a different machine "
            "reproduced this bundle"
        )
    elif independent:
        state = TrustState.COMMUNITY_VALIDATED
        reason = (
            f"{len(independent)} unsigned attestation(s) from a different machine reproduced "
            "this bundle. Unsigned records who says so, which is not proof"
        )
    else:
        state = TrustState.LOCAL
        if same_machine:
            reason = (
                f"{len(same_machine)} attestation(s) reproduced this bundle on the machine "
                "that produced it. That demonstrates determinism, not independent "
                "reproduction, and LOCAL already says it"
            )
        elif unknown_machine:
            reason = (
                f"{len(unknown_machine)} attestation(s) reproduced this bundle, but neither "
                "record states its hardware, so independence cannot be established"
            )
        elif sound:
            reason = "attestations exist, but none reports a successful reproduction"
        else:
            reason = "no sound attestation for this bundle"

    return {
        "state": state.value,
        "reason": reason,
        "sound_attestations": len(sound),
        "rejected": rejected,
        "independent": len(independent),
        "same_machine": len(same_machine),
        "unknown_machine": len(unknown_machine),
        "signed": len(signed_independent),
        # MAINTAINER_VERIFIED is never reached automatically. It means a person
        # with authority over this project looked; no amount of machine evidence
        # is that, and awarding it here would make it worthless.
        "note": (
            "MAINTAINER_VERIFIED is never awarded by this function. It records a human "
            "judgement, and a machine cannot make one."
        ),
    }


def render_markdown(
    bundle: str, attestations: list[dict[str, Any]], promotion: dict[str, Any]
) -> str:
    """A chain-of-custody view: who ran what, where, and whether it is proof."""
    lines = [
        f"### Reproduction attestations for `{bundle}`",
        "",
        f"**Supported trust state: {promotion['state']}** — {promotion['reason']}",
        "",
    ]
    if not attestations:
        lines.append("No attestations. This bundle has been reproduced by nobody but its author.")
        return "\n".join(lines) + "\n"

    lines += [
        "| Attester | When | Outcome | Machine | Signed |",
        "|---|---|---|---|---|",
    ]
    for attestation in attestations:
        lines.append(
            f"| {attestation.get('attester', '?')} "
            f"| {attestation.get('attested_at', '?')} "
            f"| {attestation.get('outcome', '?')} "
            f"| {attestation.get('_machine', 'unknown')} "
            f"| {'yes' if attestation.get('signed') else 'no'} |"
        )
    lines += [
        "",
        "An unsigned attestation records who *says* they reproduced this bundle. That is "
        "how most reproduction works in practice, and it is not the same as proof.",
        "",
        promotion["note"],
    ]
    return "\n".join(lines) + "\n"
