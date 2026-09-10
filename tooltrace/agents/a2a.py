"""A2A Agent Cards: what one has to declare, and what a signature on it proves.

An Agent Card is the A2A equivalent of `tools/list` -- a JSON document at
`/.well-known/agent-card.json` saying who an agent is, what it can do, and how
to reach it. A2A v1.0 added JWS signatures, which is what makes the card a
trust artifact rather than a self-description.

Two things are checked here, and they are separate on purpose.

**Conformance** is structural: does the card declare the fields a client needs
before it can talk to this agent at all? A missing `url` makes the card
unusable; a missing skill `description` makes it unhelpful. Those are different
severities and the report keeps them apart, exactly as `mcp_conformance` does.

**Signature** is about provenance, and the interesting part is what it does
*not* establish. A JWS proves the card was signed by whoever holds the key. It
proves nothing at all about *which* key that should be -- so a verifier that
fetches the key from a URL inside the document it is verifying has checked that
the document agrees with itself. This module will not do that: the key comes
from the caller or the card is reported as unverified. That refusal is the whole
value of the check.

Algorithms: HS256 is verified with the standard library. Asymmetric algorithms
need `cryptography`, which is not a dependency of this package, so a card signed
with RS256 or ES256 is reported as `no_verifier` rather than as valid or
invalid. Reporting "unverified" honestly beats reporting "verified" on the
strength of a check that did not happen.

HS256 on a *public* agent card is itself a finding, and the report says so: a
symmetric key means everyone who can verify the card can also forge one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

#: Fields A2A v1.0 requires on every Agent Card.
REQUIRED_FIELDS: tuple[str, ...] = (
    "protocolVersion",
    "name",
    "description",
    "url",
    "version",
    "capabilities",
    "defaultInputModes",
    "defaultOutputModes",
    "skills",
)

#: Fields a card is usable without and poorer for.
RECOMMENDED_FIELDS: tuple[str, ...] = (
    "provider",
    "documentationUrl",
    "securitySchemes",
    "preferredTransport",
)

REQUIRED = "required"
RECOMMENDED = "recommended"

UNSIGNED = "unsigned"
MALFORMED = "malformed"
NO_VERIFIER = "no_verifier"
NO_KEY = "no_key"
VERIFIED = "verified"
INVALID = "invalid"

#: Algorithms this package can verify without an optional dependency.
STDLIB_ALGORITHMS = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}


@dataclass(frozen=True)
class CardCheck:
    name: str
    severity: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity,
            "passed": self.passed,
            "detail": self.detail,
        }


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def canonical_payload(card: dict[str, Any]) -> str:
    """The bytes a signature covers: the card without its own signatures.

    Sorted keys and no whitespace, because a signature over a document has to
    be a signature over one specific serialization of it. Two implementations
    that disagree about key order produce signatures that never verify against
    each other, and the failure looks like a bad key.
    """
    body = {key: value for key, value in card.items() if key != "signatures"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def card_conformance(card: dict[str, Any]) -> list[CardCheck]:
    """Structural checks: can a client use this card, and how well?"""
    checks: list[CardCheck] = []

    for field in REQUIRED_FIELDS:
        value = card.get(field)
        present = value not in (None, "", [], {})
        checks.append(
            CardCheck(
                f"declares_{field}",
                REQUIRED,
                present,
                f"{field}: {'present' if present else 'missing'}",
            )
        )

    for field in RECOMMENDED_FIELDS:
        present = card.get(field) not in (None, "", [], {})
        checks.append(
            CardCheck(
                f"declares_{field}",
                RECOMMENDED,
                present,
                f"{field}: {'present' if present else 'missing'}",
            )
        )

    skills = card.get("skills")
    if isinstance(skills, list) and skills:
        named = [s for s in skills if isinstance(s, dict) and s.get("id") and s.get("name")]
        checks.append(
            CardCheck(
                "every_skill_is_identified",
                REQUIRED,
                len(named) == len(skills),
                f"{len(named)} of {len(skills)} skills carry an id and a name",
            )
        )
        described = [s for s in skills if isinstance(s, dict) and s.get("description")]
        checks.append(
            CardCheck(
                "every_skill_is_described",
                RECOMMENDED,
                len(described) == len(skills),
                f"{len(described)} of {len(skills)} skills describe themselves",
            )
        )

    url = card.get("url")
    if isinstance(url, str) and url:
        # An agent reached over plain HTTP can be rewritten in transit, which
        # makes every capability it declares unverifiable. Recommended rather
        # than required, because a card served on a private network is a real
        # and legitimate case.
        checks.append(
            CardCheck(
                "endpoint_is_https",
                RECOMMENDED,
                url.startswith("https://"),
                f"url scheme: {url.split(':', 1)[0]}",
            )
        )

    return checks


def _select_key(header: dict[str, Any], keys: dict[str, bytes] | None) -> bytes | None:
    if not keys:
        return None
    kid = header.get("kid")
    if isinstance(kid, str) and kid in keys:
        return keys[kid]
    if len(keys) == 1:
        return next(iter(keys.values()))
    return None


def signature_report(
    card: dict[str, Any],
    keys: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """What the signatures on this card establish, given the keys supplied.

    *keys* maps a `kid` to a secret. It comes from the caller and never from
    the card: a signature checked against a key the document itself names
    proves that the document agrees with itself, which is not what anyone
    reading a signature wants to know.
    """
    signatures = card.get("signatures")
    if not signatures:
        return {
            "state": UNSIGNED,
            "signatures": 0,
            "statement": (
                "the card carries no signature, so it is a self-description -- "
                "everything in it is a claim by whoever served it"
            ),
        }
    if not isinstance(signatures, list):
        return {
            "state": MALFORMED,
            "signatures": 0,
            "statement": "`signatures` is present but is not a list",
        }

    payload = canonical_payload(card)
    results: list[dict[str, Any]] = []

    for index, entry in enumerate(signatures):
        if not isinstance(entry, dict) or "protected" not in entry or "signature" not in entry:
            results.append(
                {"index": index, "state": MALFORMED, "detail": "missing protected or signature"}
            )
            continue
        try:
            header = json.loads(_b64url_decode(str(entry["protected"])))
        except (ValueError, TypeError):
            results.append(
                {"index": index, "state": MALFORMED, "detail": "protected header is not JSON"}
            )
            continue
        algorithm = str(header.get("alg", ""))
        signing_input = f"{entry['protected']}.{_b64url_encode(payload.encode('utf-8'))}"

        if algorithm not in STDLIB_ALGORITHMS:
            results.append(
                {
                    "index": index,
                    "state": NO_VERIFIER,
                    "algorithm": algorithm,
                    "detail": (
                        f"{algorithm or '(none declared)'} needs an asymmetric verifier this "
                        "package does not bundle; reported unverified rather than assumed valid"
                    ),
                }
            )
            continue

        key = _select_key(header, keys)
        if key is None:
            results.append(
                {
                    "index": index,
                    "state": NO_KEY,
                    "algorithm": algorithm,
                    "detail": (
                        "no key supplied for this signature. A key taken from the card "
                        "would only prove the card agrees with itself"
                    ),
                }
            )
            continue

        expected = hmac.new(
            key, signing_input.encode("ascii"), STDLIB_ALGORITHMS[algorithm]
        ).digest()
        try:
            provided = _b64url_decode(str(entry["signature"]))
        except (ValueError, TypeError):
            results.append(
                {"index": index, "state": MALFORMED, "detail": "signature is not base64url"}
            )
            continue
        ok = hmac.compare_digest(expected, provided)
        results.append(
            {
                "index": index,
                "state": VERIFIED if ok else INVALID,
                "algorithm": algorithm,
                "detail": (
                    "signature matches the canonical payload"
                    if ok
                    else "signature does not match; the card was changed after signing, "
                    "or this is the wrong key"
                ),
            }
        )

    states = [r["state"] for r in results]
    if INVALID in states:
        overall = INVALID
    elif MALFORMED in states:
        overall = MALFORMED
    elif VERIFIED in states:
        overall = VERIFIED
    elif NO_KEY in states:
        overall = NO_KEY
    else:
        overall = NO_VERIFIER

    symmetric = [r for r in results if str(r.get("algorithm", "")).startswith("HS")]
    return {
        "state": overall,
        "signatures": len(results),
        "detail": results,
        "statement": _signature_statement(overall, len(results), bool(symmetric)),
    }


def _signature_statement(state: str, count: int, symmetric: bool) -> str:
    base = {
        VERIFIED: f"{count} signature(s) verified against the key supplied",
        INVALID: "a signature does not match: the card changed after signing, or the key is wrong",
        MALFORMED: "a signature is not a well-formed JWS",
        NO_KEY: "signed, and no key was supplied, so this is a signature nobody has checked",
        NO_VERIFIER: (
            "signed with an algorithm this package cannot verify without an optional "
            "dependency; reported unverified rather than assumed valid"
        ),
        UNSIGNED: "unsigned",
    }[state]
    if symmetric:
        base += (
            ". The algorithm is symmetric: everyone who can verify this card can also "
            "forge one, which makes it unsuitable for a public agent card"
        )
    return base + "."


def report(card: dict[str, Any], keys: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Conformance and provenance, kept apart because they answer different questions."""
    checks = card_conformance(card)
    required_failures = [c.name for c in checks if c.severity == REQUIRED and not c.passed]
    recommended_failures = [c.name for c in checks if c.severity == RECOMMENDED and not c.passed]
    signature = signature_report(card, keys)

    return {
        # `ok` is conformance only. A card can be perfectly formed and
        # unsigned, and calling that a failure would mean every card in the
        # ecosystem fails -- signatures arrived in v1.0.
        "ok": not required_failures,
        "required_failures": required_failures,
        "recommended_failures": recommended_failures,
        "checks": [c.to_dict() for c in checks],
        "signature": signature,
        "statement": (
            (
                "the card declares everything a client needs"
                if not required_failures
                else f"{len(required_failures)} required field(s) missing: "
                f"{', '.join(required_failures)}"
            )
            + "; "
            + signature["statement"]
        ),
    }
