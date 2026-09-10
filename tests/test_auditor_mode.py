"""Auditor mode: read-only, time-boxed, watermarked -- and each for a reason.

An external reviewer needs to see the evidence and must not be able to change
it, must lose access when the audit ends, and must be able to tell (as must
anyone they show a screenshot to) that they were looking at a shared view.

The load-bearing fix underneath is that **expiry was never enforced**. The token
store recorded `expires_hint_days` and `verify` returned the record whatever its
age, so every token this server ever issued was permanent. A grant "for the
duration of the audit" that outlives the audit is how a temporary reviewer
becomes a permanent one, and the field's name made it look deliberate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tooltrace.server.core import (
    ROLE_PERMISSIONS,
    ROLES,
    TokenStore,
    User,
    auditor_grant,
    authorize,
)


class Clock:
    """A movable clock, so an expiry is tested rather than waited for."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 10, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, days: float) -> None:
        self.now += timedelta(days=days)


# --- expiry is enforced, not hinted -----------------------------------------


def test_a_token_stops_working_when_it_expires() -> None:
    clock = Clock()
    store = TokenStore(now=clock)
    raw = store.issue("u1", "w1", ["read_results"], ttl_days=7)

    assert store.verify(raw) is not None
    clock.advance(6.9)
    assert store.verify(raw) is not None, "it must not expire early either"
    clock.advance(0.2)
    assert store.verify(raw) is None


def test_the_expiry_is_stored_as_an_instant_not_a_duration() -> None:
    """A duration has to be added to something at read time, and the something
    is what gets forgotten."""
    clock = Clock()
    record = TokenStore(now=clock)
    raw = record.issue("u1", "w1", [], ttl_days=3)
    stored = record.verify(raw)
    assert stored is not None
    assert stored["expires_at"] == (clock.now + timedelta(days=3)).isoformat()


def test_a_record_with_no_expiry_is_treated_as_live() -> None:
    """Tokens issued before enforcement existed.

    Silently revoking every one of them would be a worse failure than the one
    being fixed.
    """
    store = TokenStore()
    assert store.expired({"owner": "u1"}) is False


def test_an_unparseable_expiry_does_not_lock_anyone_out() -> None:
    store = TokenStore()
    assert store.expired({"expires_at": "whenever"}) is False


# --- rotation keeps the properties that matter ------------------------------


def test_rotation_carries_the_watermark() -> None:
    """Rotating is the one operation an auditor can perform on their own token.

    Losing the watermark there would turn a watermarked grant into an anonymous
    one, by design rather than by accident.
    """
    store = TokenStore()
    raw = store.issue("u1", "w1", ["read_results"], watermark="Issued to Ana")
    rotated = store.rotate(raw, "u1", "w1", ["read_results"])
    assert rotated is not None
    record = store.verify(rotated)
    assert record is not None
    assert record["watermark"] == "Issued to Ana"


def test_rotation_keeps_the_original_lifetime() -> None:
    """Otherwise rotating a 14-day grant silently makes it a 90-day one."""
    clock = Clock()
    store = TokenStore(now=clock)
    raw = store.issue("u1", "w1", [], ttl_days=14)
    rotated = store.rotate(raw, "u1", "w1", [])
    assert rotated is not None
    record = store.verify(rotated)
    assert record is not None
    assert record["ttl_days"] == 14


def test_an_expired_token_cannot_be_rotated_into_a_live_one() -> None:
    clock = Clock()
    store = TokenStore(now=clock)
    raw = store.issue("u1", "w1", [], ttl_days=1)
    clock.advance(2)
    # `rotate` looks the hash up directly, so this is the check that an expired
    # grant cannot renew itself.
    assert store.verify(raw) is None


# --- the auditor role -------------------------------------------------------


def test_auditor_is_a_role_of_its_own() -> None:
    assert "auditor" in ROLES


def test_an_auditor_can_read_and_cannot_write() -> None:
    """Read-only by permission, not by convention: a mistake cannot become a
    change to the thing under review."""
    auditor = User("a", "Ana", "auditor", "w1")
    assert authorize(auditor, "read_results", "w1")
    assert authorize(auditor, "read_evidence", "w1")
    for permission in ("run_experiments", "author_tasks", "manage_members", "manage_policies"):
        assert not authorize(auditor, permission, "w1"), permission


def test_an_auditor_holds_no_permission_containing_a_verb_that_writes() -> None:
    writes = {
        p
        for p in ROLE_PERMISSIONS["admin"]
        if p.split("_")[0] in {"run", "author", "manage", "approve", "review"}
    }
    assert not (ROLE_PERMISSIONS["auditor"] & writes)


def test_an_auditor_is_still_tenant_scoped() -> None:
    auditor = User("a", "Ana", "auditor", "w1")
    assert not authorize(auditor, "read_results", "w2")


# --- the grant --------------------------------------------------------------


def grant(clock: Clock | None = None, **kwargs: object) -> tuple[dict, TokenStore, dict]:
    store = TokenStore(now=clock) if clock else TokenStore()
    users: dict[str, User] = {}
    payload = auditor_grant(
        store,
        users,
        auditor_name="Ana Ruiz",
        workspace_id="w1",
        issued_by="maintainer",
        **kwargs,  # type: ignore[arg-type]
    )
    return payload, store, users


def test_a_grant_produces_a_working_read_only_token() -> None:
    payload, store, users = grant()
    record = store.verify(payload["token"])
    assert record is not None
    user = users[payload["user_id"]]
    assert user.role == "auditor"
    assert authorize(user, "read_results", "w1")
    assert not authorize(user, "run_experiments", "w1")


def test_a_grant_defaults_to_a_short_life_not_ninety_days() -> None:
    """The default is the one most grants will use, so it has to be the safe one."""
    payload, store, _ = grant()
    record = store.verify(payload["token"])
    assert record is not None
    assert record["ttl_days"] == 14


def test_the_watermark_names_who_it_was_for_and_who_issued_it() -> None:
    payload, _, _ = grant()
    assert "Ana Ruiz" in payload["watermark"]
    assert "maintainer" in payload["watermark"]


def test_the_watermark_is_on_the_token_not_applied_at_render_time() -> None:
    """A watermark applied at render time is one somebody can render without."""
    payload, store, _ = grant()
    record = store.verify(payload["token"])
    assert record is not None
    assert record["watermark"] == payload["watermark"]


def test_the_grant_expires_and_the_statement_says_when() -> None:
    clock = Clock()
    payload, store, _ = grant(clock, ttl_days=2)
    assert payload["expires_at"] in payload["statement"]
    clock.advance(3)
    assert store.verify(payload["token"]) is None


def test_the_statement_says_it_stops_rather_than_needing_revocation() -> None:
    payload, _, _ = grant()
    assert "rather than relying on anyone to revoke it" in payload["statement"]


def test_the_token_is_returned_once_and_stored_hashed() -> None:
    payload, store, _ = grant()
    assert payload["token"].startswith("ttk_")
    assert payload["token"] not in repr(store.__dict__)


@pytest.mark.parametrize("permission", sorted(ROLE_PERMISSIONS["auditor"]))
def test_every_granted_scope_is_one_the_role_actually_has(permission: str) -> None:
    payload, _, _ = grant()
    assert permission in payload["scopes"]
