"""Scoring production traffic as it arrives, without re-scoring what you have.

"Online evaluation" in an offline-first tool means *incremental*: run it on a
schedule, process what is new since last time, and append to a rolling window.
Nothing here holds a connection open or watches a socket, because a benchmark
that runs a daemon is a benchmark somebody has to operate.

The pieces already existed -- `ingest` reads a trace, `sampling` decides which to
keep, the trace scorers grade one, `drift` compares two windows. What was
missing is the thing that ties them together and, more importantly, the thing
that stops the result being nonsense over time.

## The cursor records the policy, not just the position

The obvious cursor is "where did I get to". That is not enough, and the reason
is the point of this module:

**A window whose sampling policy changed midway is not comparable to itself.**
Switch from uniform-at-1% to stratified and the observed failure rate jumps,
because the sample changed -- not because anything in production did. A drift
report over that window would name a date, describe a real-looking shift, and be
entirely an artifact of the pipeline.

So the cursor carries the policy fingerprint, and a change **starts a new
window** rather than continuing the old one. The old window stays readable; the
two are simply not spliced into one series. That is inconvenient exactly once,
which is better than a trend line that lies quietly forever.

A cursor is also refused when it comes from a different harness version in a way
that changes scoring. Two halves of a window graded by different code are the
same problem wearing different clothes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tooltrace.core.versions import FRAMEWORK_VERSION

CURSOR_NAME = "online-cursor.json"

CONTINUED = "continued"
NEW_WINDOW = "new_window"
FIRST_RUN = "first_run"


@dataclass
class Cursor:
    """Where the last pass got to, and under what rules."""

    #: Ids already processed. A set rather than a high-water mark: traces do not
    #: arrive in order, and a mark would silently skip anything that landed late.
    seen: set[str] = field(default_factory=set)
    policy_fingerprint: str = ""
    framework_version: str = ""
    window_started_at: str = ""
    windows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "seen": sorted(self.seen),
            "policy_fingerprint": self.policy_fingerprint,
            "framework_version": self.framework_version,
            "window_started_at": self.window_started_at,
            "windows": self.windows,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Cursor:
        return cls(
            seen=set(raw.get("seen") or []),
            policy_fingerprint=str(raw.get("policy_fingerprint") or ""),
            framework_version=str(raw.get("framework_version") or ""),
            window_started_at=str(raw.get("window_started_at") or ""),
            windows=int(raw.get("windows") or 0),
        )


def policy_fingerprint(policy: str, rate: float, seed: int) -> str:
    """A stable identifier for "the rules this window was sampled under".

    Hashed rather than stored as prose so a comparison is exact: two windows are
    spliceable or they are not, and a fuzzy match on a description would let a
    changed rate through as "close enough".
    """
    payload = json.dumps({"policy": policy, "rate": rate, "seed": seed}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_cursor(directory: Path) -> Cursor | None:
    path = directory / CURSOR_NAME
    if not path.is_file():
        return None
    try:
        return Cursor.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError):
        # A corrupt cursor starts a new window rather than crashing the pass or
        # silently re-scoring everything. Losing continuity is recoverable;
        # splicing an unknown history into a trend line is not.
        return None


def save_cursor(directory: Path, cursor: Cursor) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CURSOR_NAME
    path.write_text(json.dumps(cursor.to_dict(), indent=2), encoding="utf-8")
    return path


def _trace_id(trace: dict[str, Any]) -> str:
    return str(trace.get("trace_id") or trace.get("id") or "")


def pass_over(
    traces: list[dict[str, Any]],
    *,
    directory: Path,
    policy: str = "stratified",
    rate: float = 0.01,
    seed: int = 0,
    now: str = "",
) -> dict[str, Any]:
    """One incremental pass: skip what is done, sample the rest, report the window."""
    from tooltrace.ingest.sampling import sample

    fingerprint = policy_fingerprint(policy, rate, seed)
    cursor = load_cursor(directory)

    if cursor is None:
        state, reason = FIRST_RUN, "no cursor here yet"
        cursor = Cursor(window_started_at=now, windows=1)
    elif cursor.policy_fingerprint != fingerprint:
        state = NEW_WINDOW
        reason = (
            "the sampling policy changed. A window sampled two ways is not comparable to "
            "itself: the observed rate moves because the sample moved, not because "
            "production did, and a drift report over it would describe an artifact of "
            "this pipeline as a change in the agent"
        )
        cursor = Cursor(seen=cursor.seen, window_started_at=now, windows=cursor.windows + 1)
    elif cursor.framework_version != FRAMEWORK_VERSION:
        state = NEW_WINDOW
        reason = (
            f"the harness version changed ({cursor.framework_version} -> "
            f"{FRAMEWORK_VERSION}). Two halves of a window graded by different code are "
            "the same problem as two sampling policies"
        )
        cursor = Cursor(seen=cursor.seen, window_started_at=now, windows=cursor.windows + 1)
    else:
        state, reason = CONTINUED, "same policy and harness version as the last pass"

    # Ids, not a high-water mark: traces do not arrive in order, and a mark
    # would silently skip anything that landed late.
    fresh = [t for t in traces if _trace_id(t) and _trace_id(t) not in cursor.seen]
    unidentified = [t for t in traces if not _trace_id(t)]

    chosen = sample(fresh, policy=policy, rate=rate, seed=seed)
    for trace in fresh:
        cursor.seen.add(_trace_id(trace))
    cursor.policy_fingerprint = fingerprint
    cursor.framework_version = FRAMEWORK_VERSION

    return {
        "state": state,
        "reason": reason,
        "window": cursor.windows,
        "window_started_at": cursor.window_started_at,
        "seen_total": len(cursor.seen),
        "arrived": len(traces),
        "already_processed": len(traces) - len(fresh) - len(unidentified),
        "unidentified": len(unidentified),
        "selected": chosen["kept"],
        "to_score": chosen["traces"],
        "sampling": {k: v for k, v in chosen.items() if k != "traces"},
        "cursor": cursor,
        "statement": _statement(state, traces, fresh, chosen, unidentified, cursor),
    }


def _statement(
    state: str,
    traces: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    chosen: dict[str, Any],
    unidentified: list[dict[str, Any]],
    cursor: Cursor,
) -> str:
    parts = [
        f"{len(traces)} trace(s) arrived, {len(fresh)} new, {chosen['kept']} selected for scoring"
    ]
    if unidentified:
        parts.append(
            f"{len(unidentified)} carried no id and were skipped -- an id is what makes a pass "
            "incremental, and without one a trace would be re-scored on every run"
        )
    if state == NEW_WINDOW:
        parts.append(
            f"**this starts window {cursor.windows}**; it is not spliced onto the previous one"
        )
    elif state == FIRST_RUN:
        parts.append("first pass in this directory")
    return "; ".join(parts) + "."


def windows_are_comparable(a: Cursor, b: Cursor) -> dict[str, Any]:
    """Can two windows be read as one series?

    Asked explicitly rather than assumed, because the answer is usually yes and
    the case where it is no is the one that produces a confident wrong reading.
    """
    problems: list[str] = []
    if a.policy_fingerprint != b.policy_fingerprint:
        problems.append("sampled under different policies")
    if a.framework_version != b.framework_version:
        problems.append(
            f"graded by different harness versions ({a.framework_version} vs {b.framework_version})"
        )
    return {
        "comparable": not problems,
        "problems": problems,
        "statement": (
            "these windows can be read as one series"
            if not problems
            else "these windows are not one series: " + "; ".join(problems)
        ),
    }
