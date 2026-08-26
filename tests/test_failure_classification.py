"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

from tooltrace.core.models import FailureReason, TraceEvent


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestClassify:
    def test_timeout(self) -> None:
        from tooltrace.failures import classify

        c = classify([], timed_out=True)
        assert c.reason is FailureReason.timeout and c.rule == "wall_timeout"

    def test_denied(self) -> None:
        from tooltrace.failures import classify

        c = classify([_ev("tool_result", {"status": "denied", "tool": "shell"})])
        assert c.reason is FailureReason.policy_violation

    def test_invalid_tool(self) -> None:
        from tooltrace.failures import classify

        c = classify(
            [_ev("tool_result", {"status": "error", "data": {"invalid": True}, "tool": "x"})]
        )
        assert c.reason is FailureReason.hallucinated_resource

    def test_loop(self) -> None:
        from tooltrace.failures import classify

        evs = [
            _ev("tool_result", {"status": "error", "tool": "read_file", "error": "boom"})
            for _ in range(3)
        ]
        c = classify(evs)
        assert c.reason is FailureReason.loop

    def test_subprocess_timeout_text(self) -> None:
        from tooltrace.failures import classify

        c = classify(
            [_ev("tool_result", {"status": "error", "error": "[timeout] command timed out"})]
        )
        assert c.reason is FailureReason.timeout

    def test_spawn_error(self) -> None:
        from tooltrace.failures import classify

        c = classify([_ev("tool_result", {"status": "error", "error": "[spawn error] nope"})])
        assert c.reason is FailureReason.environment

    def test_bad_arguments(self) -> None:
        from tooltrace.failures import classify

        c = classify([_ev("tool_result", {"status": "error", "error": "path must be a string"})])
        assert c.reason is FailureReason.bad_arguments

    def test_injected_fault(self) -> None:
        from tooltrace.failures import classify

        c = classify(
            [
                _ev(
                    "tool_result",
                    {
                        "status": "error",
                        "error": "injected transient failure",
                        "data": {"injected": True},
                    },
                )
            ]
        )
        assert c.reason is FailureReason.execution and c.rule == "unrecovered_injected_fault"

    def test_max_steps(self) -> None:
        from tooltrace.failures import classify

        c = classify([], finish_reason="max_steps")
        assert c.reason is FailureReason.context_loss

    def test_adapter_error(self) -> None:
        from tooltrace.failures import classify

        c = classify([], finish_reason="error")
        assert c.reason is FailureReason.planning

    def test_verification(self) -> None:
        from tooltrace.failures import classify

        c = classify([], score_total=0.5)
        assert c.reason is FailureReason.verification

    def test_no_failure(self) -> None:
        from tooltrace.failures import classify

        c = classify([], score_total=1.0)
        assert c.reason is FailureReason.none
