"""Trajectory-quality metrics computed from traces/results (features 32, 37,
38, 39, 40, 41).

Inputs are deliberately plain structures (lists of dicts) so these metrics run
against live traces, stored bundles, or replayed trajectories identically.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any


def efficiency_metrics(result: dict[str, Any]) -> dict[str, float | None]:
    """Successful outcome per tool call / step / token / wall-time unit
    (feature 32). Returns None components when inputs are missing so callers
    never confuse 'unknown' with zero."""
    success = bool(result.get("success"))
    score_obj = result.get("score")
    score = float(score_obj.get("total", 0.0)) if isinstance(score_obj, dict) else 0.0
    tool_calls = result.get("tool_calls") or 0
    steps = result.get("steps") or 0
    wall_ms = result.get("wall_ms") or 0
    usage = result.get("usage") or {}
    tokens = (usage.get("tokens") or {}).get("total_tokens") if isinstance(usage, dict) else None

    def ratio(num: float, den: float) -> float | None:
        return round(num / den, 6) if den else None

    return {
        "success_per_tool_call": ratio(1.0 if success else 0.0, float(tool_calls)),
        "score_per_tool_call": ratio(score, float(tool_calls)),
        "score_per_step": ratio(score, float(steps)),
        "score_per_1k_tokens": ratio(score * 1000.0, float(tokens)) if tokens else None,
        "score_per_second": ratio(score * 1000.0, float(wall_ms)),
    }


def loop_detection(tool_events: Sequence[dict[str, Any]], window: int = 4) -> dict[str, Any]:
    """Detect stagnation: repeated semantic tool calls with unchanged state
    (feature 38). Two calls are semantically equal when tool + args match."""
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for ev in tool_events:
        args = ev.get("args_summary") or ev.get("args") or ""
        seen[(str(ev.get("tool")), str(args))] += 1
    repeats = sum(1 for count in seen.values() if count >= window)
    cyclical = False
    if len(tool_events) >= max(window, 3):
        cyclical = any(
            len({str(e.get("tool")) for e in tool_events[i : i + window]}) <= 2
            for i in range(len(tool_events) - window + 1)
        )
    return {
        "stagnant_repeats": repeats,
        "cyclical_plan": cyclical,
        "is_stagnating": repeats > 0 or cyclical,
    }


def hallucinated_resources(tool_events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Count references to nonexistent files/APIs/commands/tools (feature 40):
    'not found' errors, unknown-tool denials, command-not-found exits."""
    patterns = ("no such file", "not found", "does not exist", "unknown tool", "command not found")
    hits: list[dict[str, Any]] = []
    for ev in tool_events:
        blob = f"{ev.get('error', '')} {ev.get('result_summary', '')}".lower()
        if any(p in blob for p in patterns):
            hits.append(
                {"seq": ev.get("seq"), "tool": ev.get("tool"), "signal": blob.strip()[:120]}
            )
    return {"count": len(hits), "events": hits}


def context_retention(turns: Sequence[dict[str, Any]], facts: Sequence[str]) -> dict[str, Any]:
    """Measure whether facts introduced earlier survive to later turns
    (feature 41). Each fact is a substring expected in later messages/args."""
    if not facts:
        return {"retention_rate": None, "lost_facts": []}
    later_text = " ".join(str(t.get("text", "")) for t in turns[len(turns) // 2 :]).lower()
    lost = [f for f in facts if f.lower() not in later_text]
    kept = len(facts) - len(lost)
    return {"retention_rate": round(kept / len(facts), 4), "lost_facts": lost}


def confusion_matrix(
    rows: Sequence[tuple[str, str]], labels: Sequence[str] | None = None
) -> dict[str, Any]:
    """Tool-selection confusion matrix by task class / failure category
    (feature 39). ``rows`` are (expected, actual) label pairs."""
    actual_labels = sorted({r[0] for r in rows} | {r[1] for r in rows})
    use = list(labels) if labels else actual_labels
    index = {label: i for i, label in enumerate(use)}
    matrix = [[0] * len(use) for _ in use]
    for expected, actual in rows:
        if expected in index and actual in index:
            matrix[index[expected]][index[actual]] += 1
    diag = sum(matrix[i][i] for i in range(len(use)))
    total = sum(sum(r) for r in matrix)
    per_label = {}
    for i, label in enumerate(use):
        row_total = sum(matrix[i])
        per_label[label] = round(matrix[i][i] / row_total, 4) if row_total else None
    return {
        "labels": use,
        "matrix": matrix,
        "accuracy": round(diag / total, 4) if total else None,
        "per_label_accuracy": per_label,
    }


def verification_quality(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Did the agent run appropriate checks before declaring success?
    (feature 37): verification calls after the last mutating call."""
    mutating = {"write_file", "patch_file", "shell", "git"}
    verifying = {"test_runner"}
    last_mutate_idx = -1
    verify_after = 0
    for i, ev in enumerate(events):
        tool = str(ev.get("tool"))
        if tool in mutating and ev.get("status") == "ok":
            last_mutate_idx = i
        elif tool in verifying and i > last_mutate_idx:
            verify_after += 1
    finished_cleanly = any(
        str(ev.get("type")) == "task_end"
        and isinstance(ev.get("payload"), dict)
        and ev["payload"].get("success")
        for ev in events
    )
    return {
        "verified_after_last_change": verify_after > 0,
        "verification_calls_after_change": verify_after,
        "claimed_success_without_verification": bool(finished_cleanly and verify_after == 0),
    }


def failure_taxonomy_counts(results: Sequence[dict[str, Any]]) -> Counter[str]:
    return Counter(str(r.get("failure_reason", "none")) for r in results)
