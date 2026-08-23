"""Tests for protocol v2, governance artifacts, lint/dry-run, suites and the
new metrics modules."""

from __future__ import annotations

from tooltrace.core.models import TaskDefinition
from tooltrace.metrics import (
    bootstrap_ci,
    change_minimality,
    confusion_matrix,
    efficiency_metrics,
    hallucinated_resources,
    loop_detection,
    paired_delta,
    pass_at_k,
    pass_hat_k,
    policy_compliance,
    side_effect_correctness,
    verification_quality,
)
from tooltrace.tasks.governance import (
    build_pack_index,
    build_provenance_manifest,
    find_duplicates,
    satisfies_range,
    task_fingerprint,
    verify_provenance_manifest,
)
from tooltrace.tasks.linting import dry_run_task, lint_task
from tooltrace.tasks.suites import build_suite, sample_suite
from tooltrace.tasks.v2 import Domain, SideEffect, migrate_v1_to_v2


def make_v1(**overrides: object) -> TaskDefinition:
    base: dict[str, object] = {
        "id": "fileops/demo-task",
        "category": "fileops",
        "objective": "Copy a.txt to b.txt",
        "allowed_tools": ["read_file", "write_file"],
        "assertions": [{"type": "file_exists", "params": {"path": "b.txt"}}],
        "starting_workspace": {"a.txt": "hello"},
        "fixtures": {},
    }
    base.update(overrides)
    return TaskDefinition.model_validate(base)


# --- protocol v2 -------------------------------------------------------------


def test_v2_model_defaults_and_flags() -> None:
    t = migrate_v1_to_v2(make_v1())
    assert t.protocol_version == 2
    assert t.domain == Domain.coding
    assert SideEffect.filesystem_write in t.allowed_side_effects
    assert not t.is_dual_control() and not t.is_hitl()


def test_v2_dual_control_hitl_multiagent() -> None:
    t = migrate_v1_to_v2(make_v1())
    t.user_actions = [{"at_step": 2, "kind": "write_file", "path": "x.txt", "content": "u"}]
    t.human_steps = [{"id": "approve", "prompt": "Approve?", "expected_input": "yes"}]
    t.roles = [
        {"role": "planner"},
        {"role": "worker"},
    ]
    assert t.is_dual_control() and t.is_hitl() and t.is_multi_agent()


def test_migration_preserves_perturbations_and_long_context() -> None:
    v1 = make_v1(
        perturbations=[{"kind": "tool_failure", "params": {"tool": "read_file"}}],
        long_context=True,
    )
    v2 = migrate_v1_to_v2(v1)
    assert v2.long_horizon is True
    assert v2.metadata["migrated_from_protocol"] == 1
    assert v2.metadata["v1_perturbations"][0]["kind"] == "tool_failure"


# --- governance ---------------------------------------------------------------


def test_provenance_manifest_roundtrip_and_tamper() -> None:
    task = make_v1(fixtures={"ref.txt": "stable content"})
    m = build_provenance_manifest(task)
    assert verify_provenance_manifest(m, task) == []
    tampered = m.model_copy(deep=True)
    tampered.fixtures[0].sha256 = "deadbeef"
    assert verify_provenance_manifest(tampered, task)


def test_pack_index_semver_ranges() -> None:
    tasks = [make_v1(), make_v1(id="fileops/second-task")]
    idx = build_pack_index("fileops", tasks)
    assert idx.index_sha256
    assert len(idx.tasks) == 2
    assert satisfies_range("1.2.3", ">=1.0.0,<=2.0.0")
    assert not satisfies_range("0.9.9", ">=1.0.0")
    assert not satisfies_range("banana", ">=1.0.0")


def test_fingerprint_dedup_across_packs() -> None:
    a = make_v1()
    b = make_v1(id="otherpack/same-thing")
    c = make_v1(id="fileops/different", objective="Something entirely different")
    groups = find_duplicates([a, b, c])
    assert groups == [["fileops/demo-task", "otherpack/same-thing"]]
    assert task_fingerprint(a) == task_fingerprint(b)
    assert task_fingerprint(a) != task_fingerprint(c)


# --- lint & dry-run -----------------------------------------------------------


def test_lint_detects_unsafe_network_and_unknown_scorer() -> None:
    bad = make_v1(
        allowed_tools=["http"],
        assertions=[{"type": "nope_scorer", "params": {}}],
    )
    codes = {i.code for i in lint_task(bad)}
    assert "unsafe_network_use" in codes
    assert "unknown_scorer" in codes


def test_lint_detects_nondeterministic_fixture_and_missing_seed() -> None:
    t = make_v1(
        fixtures={"log.txt": "built at 2026-01-01 10:00:00 by CI"},
        tags=["random"],
    )
    codes = {i.code for i in lint_task(t)}
    assert "nondeterministic_fixture" in codes
    assert "missing_seed" in codes


def test_dry_run_ok_without_model() -> None:
    report = dry_run_task(make_v1())
    assert report.ok, report.problems
    assert report.checks["sandbox_cleanup"] is True


def test_dry_run_reports_unregistered_scorer() -> None:
    report = dry_run_task(make_v1(assertions=[{"type": "ghost", "params": {}}]))
    assert not report.ok
    assert any("ghost" in p for p in report.problems)


# --- suites -------------------------------------------------------------------


def test_suite_build_and_sampling_policies() -> None:
    tasks = [
        make_v1(),
        make_v1(id="fileops/two"),
        make_v1(id="gitwork/three", category="gitwork"),
    ]
    suite = build_suite("smoke", tasks)
    assert suite.suite_sha256
    fixed = sample_suite(suite, {t.id: t for t in tasks}, policy="fixed")
    assert len(fixed.selected_ids) == 3
    rand = sample_suite(suite, {t.id: t for t in tasks}, policy="seeded_random", n=2, seed=7)
    rand_again = sample_suite(suite, {t.id: t for t in tasks}, policy="seeded_random", n=2, seed=7)
    assert rand.selected_ids == rand_again.selected_ids  # deterministic
    strat = sample_suite(suite, {t.id: t for t in tasks}, policy="stratified", n=1, seed=3)
    assert len(strat.selected_ids) == 2  # one per domain stratum
    assert strat.selection_sha256


# --- reliability metrics --------------------------------------------------------


def test_pass_at_k_known_values() -> None:
    assert pass_at_k(1, 1, 1) == 1.0
    assert pass_at_k(1, 0, 1) == 0.0
    # n=2, c=1, k=1 -> 0.5 ; k=2 -> 1.0
    assert abs(pass_at_k(2, 1, 1) - 0.5) < 1e-9
    assert abs(pass_at_k(2, 1, 2) - 1.0) < 1e-9


def test_pass_hat_k_denominators() -> None:
    by_task = {
        "a": [True, False, False],  # first k=2 runs not all pass
        "b": [True, True, True],
        "c": [False],  # ineligible for k=2
    }
    assert pass_hat_k(by_task, 2) == 0.5
    assert pass_hat_k({"c": [False]}, 2) == 0.0


def test_bootstrap_ci_deterministic() -> None:
    vals = [1.0] * 8 + [0.0] * 2
    ci1 = bootstrap_ci(vals, iterations=500, seed=11)
    ci2 = bootstrap_ci(vals, iterations=500, seed=11)
    assert ci1 == ci2
    lo, hi = ci1
    assert 0.3 <= lo <= hi <= 1.0  # small-n bootstrap; wide CI expected


def test_paired_delta_and_significance() -> None:
    res = paired_delta([True, False, True], [False, False, True])
    assert res["wins"] == 1.0 and res["losses"] == 0.0 and res["ties"] == 2.0
    note = __import__(
        "tooltrace.metrics.reliability", fromlist=["significance_note"]
    ).significance_note(5, 5)
    assert "no winner" in note


# --- trajectory metrics ---------------------------------------------------------


def test_efficiency_metrics_none_vs_zero() -> None:
    r = {"success": True, "score": {"total": 1.0}, "steps": 4, "tool_calls": 3, "wall_ms": 200}
    m = efficiency_metrics(r)
    assert m["score_per_step"] == 0.25
    assert m["score_per_1k_tokens"] is None  # unknown, not zero


def test_loop_detection_stagnation() -> None:
    events = [{"tool": "read_file", "args_summary": "a.txt", "status": "ok"} for _ in range(5)]
    out = loop_detection(events, window=4)
    assert out["is_stagnating"] and out["stagnant_repeats"] >= 1
    varied = [
        {"tool": t, "args_summary": f"{t}-{i}", "status": "ok"}
        for i, t in enumerate(["read_file", "write_file", "search_text", "list_directory"])
    ]
    assert not loop_detection(varied)["is_stagnating"]


def test_hallucinated_resources() -> None:
    events = [
        {"tool": "read_file", "error": "No such file or directory: ghost.py", "result_summary": ""},
        {"tool": "deploy_cli", "error": "", "result_summary": "denied: unknown tool"},
    ]
    out = hallucinated_resources(events)
    assert out["count"] == 2


def test_confusion_matrix_accuracy() -> None:
    rows = [("read_file", "read_file"), ("write_file", "read_file"), ("git", "git")]
    cm = confusion_matrix(rows)
    assert cm["accuracy"] == round(2 / 3, 4)
    assert cm["labels"] == ["git", "read_file", "write_file"]


def test_verification_quality() -> None:
    events = [
        {"tool": "write_file", "status": "ok"},
        {"tool": "test_runner", "status": "ok"},
    ]
    good = verification_quality(events)
    assert good["verified_after_last_change"] is True
    bad = verification_quality(
        [{"tool": "write_file", "status": "ok"}, {"type": "task_end", "payload": {"success": True}}]
    )
    assert bad["claimed_success_without_verification"] is True


# --- policy metrics ---------------------------------------------------------------


def test_policy_compliance_and_side_effects() -> None:
    events = [
        {"tool": "write_file", "status": "ok"},
        {"tool": "http", "status": "denied"},
    ]
    pc = policy_compliance(events, ["write_file"], ["filesystem_write"])
    assert not pc["compliant"] and pc["denied_calls"] == 1
    se = side_effect_correctness(
        changed_paths=["out.txt", "secret.key"],
        forbidden_paths=["secret.key"],
        initial_paths=["in.txt"],
    )
    assert not se["clean"] and se["forbidden_modified"] == ["secret.key"]
    assert se["out_of_scope_created"] == ["out.txt"]


def test_change_minimality() -> None:
    m = change_minimality({"files_changed": 4, "insertions": 10, "deletions": 2}, required_scope=2)
    assert not m["minimal"] and m["excess_files"] == 2 and m["scope_ratio"] == 2.0
    ok = change_minimality({"files_changed": 1, "insertions": 3, "deletions": 1}, required_scope=1)
    assert ok["minimal"]
