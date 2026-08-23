"""Tests for analysis (baselines/trends/cohorts/clustering/leaderboards/
snapshots/signing) and sandbox infrastructure (providers/policies/faults/
clock/self-test)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tooltrace.analysis import (
    Baseline,
    InvalidationRecord,
    anti_gaming_checks,
    assert_compatible_cohorts,
    build_leaderboard,
    cluster_failures,
    cohort_key,
    detect_tampering,
    evaluate_against_baseline,
    generate_snapshot,
    manifest_checksums,
    reproducibility_score,
    sign_bundle,
    trend_analysis,
    verify_snapshot,
)
from tooltrace.sandbox.infra import (
    DeterministicClock,
    FaultInjectingProxy,
    FaultSchedule,
    NetworkPolicyProfile,
    WindowsNativeSandbox,
    docker_network_args,
    frozen_time,
    harness_self_test,
    recovery_score,
    sample_resource_usage,
)


def _result(
    agent: str, score: float, protocol: str = "2", scoring: str = "1", task_set: str = "abc"
) -> dict[str, object]:
    return {
        "agent": agent,
        "success_rate": score,
        "protocol_version": protocol,
        "scoring_version": scoring,
        "task_set_sha256": task_set,
    }


# --- cohorts -------------------------------------------------------------------


def test_incompatible_cohorts_rejected() -> None:
    a = [_result("x", 0.5, protocol="2")]
    b = [_result("y", 0.6, protocol="1")]
    with pytest.raises(ValueError):
        assert_compatible_cohorts(a, b)
    assert_compatible_cohorts(a, [_result("z", 0.7)])


# --- baselines -------------------------------------------------------------------


def test_baseline_regression_gate() -> None:
    base = Baseline(
        baseline_id="b1",
        scope="suite",
        scope_key="smoke",
        metrics={"success_rate": 0.9, "cost": 1.0},
    ).finalize()
    assert base.baseline_sha256
    ok = evaluate_against_baseline({"success_rate": 0.89, "cost": 1.0}, base)
    assert ok["ok"]
    bad = evaluate_against_baseline({"success_rate": 0.80}, base)
    assert not bad["ok"] and bad["regressions"][0]["metric"] == "success_rate"


# --- trends ------------------------------------------------------------------------


def test_trend_flags_composition_change() -> None:
    points = [
        {"version": "v1", "success_rate": 0.5, "task_set_sha256": "aaa"},
        {"version": "v2", "success_rate": 0.7, "task_set_sha256": "bbb"},
    ]
    out = trend_analysis(points)
    assert out["series"][0]["version"] == "v1"
    assert len(out["composition_warnings"]) == 1


# --- clustering -----------------------------------------------------------------------


def test_failure_clustering_deterministic() -> None:
    results = [
        {
            "success": False,
            "run_id": "r1",
            "failed_assertions": ["file_exists"],
            "first_error_tool": "write_file",
            "error_kind": "denied",
        },
        {
            "success": False,
            "run_id": "r2",
            "failed_assertions": ["file_exists"],
            "first_error_tool": "write_file",
            "error_kind": "denied",
        },
        {
            "success": False,
            "run_id": "r3",
            "failed_assertions": ["sql"],
            "first_error_tool": "db",
            "error_kind": "timeout",
        },
        {"success": True, "run_id": "r4"},
    ]
    out = cluster_failures(results)
    assert out["clustered_failures"] == 3
    assert out["clusters"][0]["size"] == 2
    again = cluster_failures(results)
    assert out == again


# --- leaderboards ------------------------------------------------------------------------


def test_leaderboard_never_mixes_cohorts() -> None:
    rows = [_result("a", 0.9), _result("b", 0.8), _result("c", 0.95, protocol="1")]
    board = build_leaderboard(rows)
    assert len(board["cohorts"]) == 2
    top = board["leaderboards"][cohort_key(_result("a", 0))][0]
    assert top["agent"] == "a"


def test_anti_gaming_detects_skipped_assertions_and_leaks() -> None:
    result = {
        "declared_assertions": ["file_exists", "output_equals"],
        "assertion_results": [
            {"type": "file_exists", "output": "ANSWER: the secret expected output"}
        ],
        "task_hashes": {"t1": "deadbeef"},
        "harness_sha256": "h1",
        "expected_harness_sha256": "h2",
    }
    out = anti_gaming_checks(result, {"t1": "cafebabe"})
    assert not out["ok"]
    assert any("absent" in p for p in out["problems"])
    assert any("leaked" in p for p in out["problems"])
    assert any("mismatch" in p for p in out["problems"])
    assert any("harness" in p for p in out["problems"])


# --- reproducibility -------------------------------------------------------------------------


def test_reproducibility_score_completeness() -> None:
    full = dict.fromkeys(
        (
            "task_pack_version",
            "protocol_version",
            "scoring_version",
            "model_revision",
            "sampling_settings",
            "sandbox_image_digest",
            "seed",
            "environment_manifest_sha256",
        ),
        "v",
    )
    assert reproducibility_score(full)["score"] == 1.0
    partial = reproducibility_score({"seed": 1})
    assert partial["score"] == pytest.approx(1 / 8)
    assert "model_revision" in partial["missing"]


# --- invalidation --------------------------------------------------------------------------------


def test_invalidation_record_roundtrip() -> None:
    rec = InvalidationRecord(
        record_id="i1", target_id="bundle-123", reason="scorer bug", superseded_by="bundle-456"
    ).finalize()
    assert rec.record_sha256
    assert rec.applies_to("bundle-123") and not rec.applies_to("other")


# --- snapshots -------------------------------------------------------------------------------------


def test_snapshot_generate_and_verify(tmp_path: Path) -> None:
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.json").write_text("{}", encoding="utf-8")
    sub = src / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("hello", encoding="utf-8")
    snap = generate_snapshot(src, tmp_path / "snapshot.json", "initial release")
    assert snap["file_count"] == 2 and snap["snapshot_sha256"]
    assert verify_snapshot(tmp_path / "snapshot.json", src) == []
    (sub / "b.txt").write_text("tampered", encoding="utf-8")
    problems = verify_snapshot(tmp_path / "snapshot.json", src)
    assert problems == ["hash mismatch: sub/b.txt"]


# --- signing (honest when cosign absent) --------------------------------------------------------------


def test_sign_bundle_reports_missing_tool_honestly(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}", encoding="utf-8")
    out = sign_bundle(bundle, signer="definitely-not-a-real-tool-xyz")
    assert out["signed"] is False and "not installed" in out["reason"]


# --- tamper-evident checksums ---------------------------------------------------------------------------


def test_manifest_checksums_detect_tampering() -> None:
    manifests = [{"id": "m1", "data": "original"}]
    recorded = manifest_checksums(manifests)
    assert detect_tampering(manifests, recorded) == []
    tampered = [{"id": "m1", "data": "modified"}]
    assert detect_tampering(tampered, recorded) == ["m1"]


# --- network policies --------------------------------------------------------------------------------------


def test_network_policy_profiles() -> None:
    offline = NetworkPolicyProfile(mode="offline")
    local = NetworkPolicyProfile(mode="local_fixtures")
    allow = NetworkPolicyProfile(mode="allowlist", allowlist=["api.example.com"])
    assert not offline.allows("localhost")
    assert local.allows("127.0.0.1") and not local.allows("evil.com")
    assert allow.allows("api.example.com") and not allow.allows("evil.com")
    assert docker_network_args(offline) == ["--network", "none"]


# --- windows sandbox ------------------------------------------------------------------------------------------


def test_windows_native_sandbox_lifecycle(tmp_path: Path) -> None:
    sb = WindowsNativeSandbox(root=tmp_path)
    ws = sb.start()
    assert ws.is_dir() and ws.exists()
    (ws / "f.txt").write_text("x", encoding="utf-8")
    assert sb.cleanup() is True
    assert not ws.exists()
    assert WindowsNativeSandbox.limitations  # limitations are documented


# --- deterministic clock ------------------------------------------------------------------------------------------


def test_deterministic_clock_never_uses_wall_time() -> None:
    with frozen_time("2030-05-05T00:00:00+00:00") as clock:
        assert clock.today_iso() == "2030-05-05"
        assert clock.today_iso() == "2030-05-05"  # frozen without an explicit step
    stepped = DeterministicClock(start="2030-05-05T00:00:00+00:00", step_s=86400.0)
    assert stepped.today_iso() == "2030-05-05"
    assert stepped.today_iso() == "2030-05-06"  # deterministic daily steps


# --- fault injection -------------------------------------------------------------------------------------------------


def test_fault_injection_transient_and_recovery() -> None:
    calls = {"n": 0}

    def tool() -> str:
        calls["n"] += 1
        return "ok"

    proxy = FaultInjectingProxy(
        tool, FaultSchedule(faults=[{"at_call": 1, "kind": "transient_error"}])
    )
    with pytest.raises(ConnectionError):
        proxy()
    assert proxy() == "ok"  # recovered on retry
    assert proxy.calls == 2
    assert recovery_score([True, False, True]) == pytest.approx(2 / 3, abs=1e-3)
    assert recovery_score([]) == 1.0


def test_fault_injection_malformed_and_restart() -> None:
    proxy = FaultInjectingProxy(
        lambda: "ok", FaultSchedule(faults=[{"at_call": 1, "kind": "malformed_response"}])
    )
    assert proxy() == "<<<not-json{{{"
    proxy2 = FaultInjectingProxy(
        lambda: "ok", FaultSchedule(faults=[{"at_call": 1, "kind": "service_restart"}])
    )
    with pytest.raises(ConnectionError):
        proxy2()
    assert proxy2() == "ok"  # restart: next call succeeds


# --- telemetry ----------------------------------------------------------------------------------------------------------


def test_resource_telemetry_returns_structured_info() -> None:
    info = sample_resource_usage()
    assert "platform" in info


# --- harness self-test ------------------------------------------------------------------------------------------------------


def test_harness_self_test_passes_on_healthy_harness(tmp_path: Path) -> None:
    class FakeSandbox:
        def start(self) -> Path:
            d = tmp_path / "ws"
            d.mkdir()
            return d

        def cleanup(self) -> None:
            import shutil

            shutil.rmtree(tmp_path / "ws", ignore_errors=True)

    report = harness_self_test(FakeSandbox, scorer=lambda v: 1.0)
    assert report["ok"], report
    assert all(report["checks"].values())


def test_harness_self_test_detects_leaked_sandbox(tmp_path: Path) -> None:
    class LeakySandbox:
        def start(self) -> Path:
            d = tmp_path / "leak"
            d.mkdir()
            return d

        def cleanup(self) -> None:
            pass  # deliberately does not clean up

    report = harness_self_test(LeakySandbox, scorer=lambda v: 0.5)
    assert report["checks"]["sandbox_cleanup"] is False
    assert not report["ok"]
