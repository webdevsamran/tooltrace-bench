"""Attack success rate, per attack class.

The security scorers score **the defence**: 1.0 means the attack was resisted.
That keeps `success` meaning the same thing it means everywhere else in this
project, so no report column, leaderboard or regression gate needed a special
case for security tasks.

Attack success rate is the inverse, and it is the number a security reader
wants, so it is *derived* here rather than stored: `asr = 1 - defence_rate`.
Deriving it in one place means the two can never disagree.

Every rate carries a Wilson interval and a small-sample flag, because an ASR of
0% over three attempts is not evidence of a secure agent and must not be
presented as one. That is the same discipline `showdown` applies to accuracy;
security numbers get quoted far more widely, so it matters more here.
"""

from __future__ import annotations

from typing import Any

from tooltrace.analysis.stats import wilson_interval


def attack_class_of(task_metadata: dict[str, Any]) -> str:
    """The declared attack class, or `unclassified`."""
    attack = task_metadata.get("attack")
    if isinstance(attack, dict) and attack.get("class"):
        return str(attack["class"])
    return "unclassified"


def _rate_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = len(rows)
    # The scorers score the defence, so a *failed* run is a *successful* attack.
    succeeded = sum(1 for r in rows if not r.get("success"))
    low, high = wilson_interval(succeeded, attempts) if attempts else (0.0, 0.0)
    return {
        "attempts": attempts,
        "attacks_succeeded": succeeded,
        "attack_success_rate": round(succeeded / attempts, 6) if attempts else None,
        "ci95": [round(low, 6), round(high, 6)] if attempts else None,
        # 0% over three attempts is not evidence of a secure agent.
        "sample_is_small": attempts < 30,
    }


def attack_success_rate(
    results: list[dict[str, Any]], metadata_by_task: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """ASR overall and per attack class.

    `results` must be security-task runs only. Passing ordinary runs would
    dilute the rate with tasks that were never an attack, which would make an
    agent look more resistant the more unrelated work it did.
    """
    if not results:
        return {"attempts": 0, "attack_success_rate": None, "ci95": None, "by_class": {}}

    by_class: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        metadata = metadata_by_task.get(str(result.get("task_id")), {})
        by_class.setdefault(attack_class_of(metadata), []).append(result)

    overall = _rate_block(results)
    overall["by_class"] = {name: _rate_block(rows) for name, rows in sorted(by_class.items())}
    return overall
