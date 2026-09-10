"""A2A Agent Cards, and what a signature on one actually establishes.

The conformance half is ordinary: does the card declare what a client needs
before it can talk to this agent, and is a missing skill description a different
severity from a missing `url`? It is, and the report keeps them apart.

The signature half is where the value is, and it is mostly a refusal. A JWS
proves the card was signed by whoever holds the key; it says nothing about which
key that should be. A verifier that fetches the key from a URL *inside the card
it is verifying* has established that the document agrees with itself, which is
not what anyone reading a signature wants to know. The key comes from the caller
here or the card is reported unverified, and the tests below pin that: an
unchecked signature must never read as a verified one.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json

from tooltrace.agents.a2a import (
    INVALID,
    NO_KEY,
    NO_VERIFIER,
    UNSIGNED,
    VERIFIED,
    canonical_payload,
    card_conformance,
    report,
    signature_report,
)

VALID_CARD = {
    "protocolVersion": "1.0",
    "name": "Ledger Reconciler",
    "description": "Reconciles ledger entries against bank statements.",
    "url": "https://agents.example.com/ledger",
    "version": "2.1.0",
    "capabilities": {"streaming": True, "pushNotifications": False},
    "defaultInputModes": ["text/plain", "application/json"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {
            "id": "reconcile",
            "name": "Reconcile a ledger",
            "description": "Match entries to statement lines and report the difference.",
        }
    ],
    "provider": {"organization": "Example Ltd", "url": "https://example.com"},
    "documentationUrl": "https://example.com/docs",
    "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
    "preferredTransport": "JSONRPC",
}

SECRET = b"a-shared-secret-nobody-should-use-for-a-public-card"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sign(card: dict, secret: bytes = SECRET, kid: str = "test-key") -> dict:
    """Produce a card carrying a genuine HS256 JWS over its canonical payload."""
    header = b64(json.dumps({"alg": "HS256", "kid": kid}).encode("utf-8"))
    payload = b64(canonical_payload(card).encode("utf-8"))
    signature = hmac.new(secret, f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    signed = copy.deepcopy(card)
    signed["signatures"] = [{"protected": header, "signature": b64(signature)}]
    return signed


# --- conformance ------------------------------------------------------------


def test_a_complete_card_passes() -> None:
    result = report(VALID_CARD)
    assert result["ok"] is True
    assert result["required_failures"] == []


def test_a_missing_required_field_fails() -> None:
    card = {k: v for k, v in VALID_CARD.items() if k != "url"}
    result = report(card)
    assert result["ok"] is False
    assert "declares_url" in result["required_failures"]


def test_a_missing_recommended_field_does_not_fail() -> None:
    """A card without documentation is poorer, not unusable."""
    card = {k: v for k, v in VALID_CARD.items() if k != "documentationUrl"}
    result = report(card)
    assert result["ok"] is True
    assert "declares_documentationUrl" in result["recommended_failures"]


def test_a_skill_with_no_id_is_a_required_failure() -> None:
    card = copy.deepcopy(VALID_CARD)
    card["skills"] = [{"name": "Nameless", "description": "no id"}]
    names = {c.name for c in card_conformance(card) if not c.passed}
    assert "every_skill_is_identified" in names


def test_a_skill_with_no_description_is_only_recommended() -> None:
    card = copy.deepcopy(VALID_CARD)
    card["skills"] = [{"id": "x", "name": "X"}]
    result = report(card)
    assert result["ok"] is True
    assert "every_skill_is_described" in result["recommended_failures"]


def test_a_plain_http_endpoint_is_flagged_without_failing() -> None:
    """A card served on a private network is a real case, so this is advice."""
    card = copy.deepcopy(VALID_CARD)
    card["url"] = "http://agents.internal/ledger"
    result = report(card)
    assert result["ok"] is True
    assert "endpoint_is_https" in result["recommended_failures"]


# --- signatures -------------------------------------------------------------


def test_an_unsigned_card_says_it_is_a_self_description() -> None:
    result = signature_report(VALID_CARD)
    assert result["state"] == UNSIGNED
    assert "claim by whoever served it" in result["statement"]


def test_a_signature_verifies_against_the_key_the_caller_supplies() -> None:
    result = signature_report(sign(VALID_CARD), {"test-key": SECRET})
    assert result["state"] == VERIFIED


def test_a_signature_with_no_key_supplied_is_not_verified() -> None:
    """The distinction that matters: unchecked must never read as checked."""
    result = signature_report(sign(VALID_CARD))
    assert result["state"] == NO_KEY
    assert "nobody has checked" in result["statement"]
    assert result["state"] != VERIFIED


def test_the_wrong_key_is_reported_as_invalid_not_unverified() -> None:
    result = signature_report(sign(VALID_CARD), {"test-key": b"a-different-secret"})
    assert result["state"] == INVALID


def test_changing_the_card_after_signing_breaks_the_signature() -> None:
    """The property the whole exercise depends on."""
    signed = sign(VALID_CARD)
    signed["url"] = "https://attacker.example/ledger"
    result = signature_report(signed, {"test-key": SECRET})
    assert result["state"] == INVALID
    assert "changed after signing" in result["detail"][0]["detail"]


def test_adding_a_skill_after_signing_breaks_the_signature() -> None:
    signed = sign(VALID_CARD)
    signed["skills"].append({"id": "exfiltrate", "name": "Exfiltrate", "description": "no"})
    assert signature_report(signed, {"test-key": SECRET})["state"] == INVALID


def test_the_signatures_field_is_not_part_of_what_it_signs() -> None:
    """Otherwise no signature could ever verify: it would have to cover itself."""
    signed = sign(VALID_CARD)
    assert canonical_payload(signed) == canonical_payload(VALID_CARD)


def test_the_payload_serialization_is_stable() -> None:
    """Two orderings produce two signatures, and the mismatch looks like a bad key."""
    reordered = dict(reversed(list(VALID_CARD.items())))
    assert canonical_payload(reordered) == canonical_payload(VALID_CARD)


def test_an_asymmetric_algorithm_is_reported_unverified_rather_than_valid() -> None:
    """`cryptography` is not a dependency, so RS256 cannot be checked here.

    Saying so beats reporting "verified" on the strength of a check that did
    not happen.
    """
    card = copy.deepcopy(VALID_CARD)
    header = b64(json.dumps({"alg": "RS256", "kid": "prod"}).encode("utf-8"))
    card["signatures"] = [{"protected": header, "signature": b64(b"not-checked")}]
    result = signature_report(card, {"prod": SECRET})
    assert result["state"] == NO_VERIFIER
    assert "unverified rather than assumed valid" in result["statement"]


def test_a_symmetric_algorithm_is_itself_a_finding() -> None:
    """Everyone who can verify an HS256 card can also forge one."""
    result = signature_report(sign(VALID_CARD), {"test-key": SECRET})
    assert "can also forge one" in result["statement"]


def test_a_malformed_signature_entry_is_reported_not_raised() -> None:
    card = copy.deepcopy(VALID_CARD)
    card["signatures"] = [{"protected": "!!!not-base64!!!", "signature": "x"}]
    assert signature_report(card)["state"] == "malformed"


def test_signatures_that_is_not_a_list_is_malformed() -> None:
    card = copy.deepcopy(VALID_CARD)
    card["signatures"] = "signed, honest"
    assert signature_report(card)["state"] == "malformed"


def test_conformance_and_signature_are_independent() -> None:
    """A perfectly formed card can be unsigned, and most in the wild are."""
    result = report(VALID_CARD)
    assert result["ok"] is True
    assert result["signature"]["state"] == UNSIGNED


# --- the CLI ----------------------------------------------------------------


def test_the_cli_reads_a_card_and_a_key(tmp_path, capsys) -> None:
    from tooltrace.cli.main import main

    path = tmp_path / "agent-card.json"
    path.write_text(json.dumps(sign(VALID_CARD)), encoding="utf-8")
    assert main(["a2a-card", str(path), "--key", f"test-key={SECRET.decode()}", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["signature"]["state"] == VERIFIED


def test_the_cli_fails_a_card_missing_a_required_field(tmp_path, capsys) -> None:
    from tooltrace.cli.main import main

    path = tmp_path / "agent-card.json"
    path.write_text(json.dumps({"name": "half a card"}), encoding="utf-8")
    assert main(["a2a-card", str(path), "--json"]) != 0
    assert "required field(s) missing" in capsys.readouterr().err


def test_the_cli_reports_a_missing_file_rather_than_raising(capsys) -> None:
    from tooltrace.cli.main import main

    assert main(["a2a-card", "no-such-card.json"]) != 0
    assert "no such card" in capsys.readouterr().err
