"""Failure classification: derive a machine-readable FailureReason from a
run's trace and statistics using transparent, ordered heuristics.

The classifier never guesses silently: the matched rule name is returned
alongside the reason so reports can explain *why* a category was assigned.
"""

from __future__ import annotations

from dataclasses import dataclass

from tooltrace.core.models import FailureReason, TraceEvent


@dataclass(frozen=True)
class Classification:
    reason: FailureReason
    rule: str
    detail: str


def classify(
    events: list[TraceEvent],
    *,
    finish_reason: str = "finished",
    timed_out: bool = False,
    score_total: float = 0.0,
) -> Classification:
    """Classify the dominant failure cause for a run.

    Ordered heuristics — first match wins:
      1. timeout            (wall clock or subprocess timeout observed)
      2. policy_violation   (denied tool calls)
      3. hallucinated_resource (unknown tool names)
      4. loop               (>=3 identical consecutive failing calls)
      5. destructive_edit   (deleted/overwrote files unrelated to objective is
                             detected by the runner via unnecessary_changes;
                             here we catch explicit deletion patterns)
      6. bad_arguments      (argument validation errors)
      7. tool_selection     (wrong-but-registered tool errors dominate)
      8. execution          (other tool failures)
      9. environment        (spawn/OS-level errors)
     10. context_loss       (finish_reason == max_steps with no tool errors)
     11. planning           (finished but assertions failed without tool errors)
     12. verification       (finished, tools fine, only verification-stage checks failed)
    """
    if timed_out:
        return Classification(FailureReason.timeout, "wall_timeout", "run exceeded task timeout")

    denied = [e for e in events if e.type == "tool_result" and e.payload.get("status") == "denied"]
    if denied:
        return Classification(
            FailureReason.policy_violation,
            "denied_tool",
            f"tool '{denied[0].payload.get('tool')}' denied by policy",
        )

    invalid = [
        e
        for e in events
        if e.type == "tool_result"
        and isinstance(e.payload.get("data"), dict)
        and e.payload["data"].get("invalid")
    ]
    if invalid:
        return Classification(
            FailureReason.hallucinated_resource,
            "unknown_tool",
            f"agent invoked unregistered tool '{invalid[0].payload.get('tool')}'",
        )

    error_results = [
        e for e in events if e.type == "tool_result" and e.payload.get("status") == "error"
    ]
    if error_results:
        # Loop detection: >=3 consecutive identical failing calls.
        signatures: list[str] = []
        for e in error_results:
            signatures.append(str(e.payload.get("tool")) + "|" + str(e.payload.get("error")))
        streak, best = 1, 1
        for i in range(1, len(signatures)):
            streak = streak + 1 if signatures[i] == signatures[i - 1] else 1
            best = max(best, streak)
        if best >= 3:
            return Classification(
                FailureReason.loop,
                "repeated_failing_call",
                f"same failing call repeated {best} times",
            )
        first = error_results[0].payload
        err_text = str(first.get("error", ""))
        if "timeout" in err_text.lower():
            return Classification(FailureReason.timeout, "subprocess_timeout", err_text[:200])
        if "spawn error" in err_text or "[spawn error]" in err_text:
            return Classification(FailureReason.environment, "spawn_error", err_text[:200])
        if "must be" in err_text.lower() or "invalid" in err_text.lower():
            return Classification(FailureReason.bad_arguments, "bad_arguments", err_text[:200])
        if first.get("data", {}).get("injected"):
            return Classification(
                FailureReason.execution,
                "unrecovered_injected_fault",
                err_text[:200],
            )
        return Classification(FailureReason.execution, "tool_error", err_text[:200])

    if finish_reason == "max_steps":
        return Classification(
            FailureReason.context_loss,
            "step_budget_exhausted",
            "step budget exhausted before completion",
        )
    if finish_reason == "error":
        return Classification(FailureReason.planning, "adapter_error", "agent adapter errored")
    if score_total < 1.0:
        return Classification(
            FailureReason.verification,
            "assertions_failed",
            f"agent finished but assertions scored {score_total:.2f}",
        )
    return Classification(FailureReason.none, "no_failure", "")
