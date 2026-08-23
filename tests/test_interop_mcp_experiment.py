"""Tests for adapter interop, MCP client/conformance and the execution engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.agents.interop import (
    AdapterCapabilities,
    CredentialResolver,
    PriceTable,
    RetryPolicy,
    adapter_health_check,
    negotiate,
    normalize_model_metadata,
    run_with_retries,
)
from tooltrace.agents.mcp import conformance_check, fake_server_command
from tooltrace.executors.experiment import (
    Coordinator,
    ExperimentManifest,
    RunState,
    default_worker_inventory,
    execute_experiment,
    idempotent_key,
    merge_run_states,
    shard_work_items,
)

# --- capability negotiation ---------------------------------------------------


def test_negotiate_ok_and_missing() -> None:
    good = negotiate(AdapterCapabilities())
    assert good["ok"] and good["missing"] == []
    bad = negotiate(AdapterCapabilities(tool_calls=False))
    assert not bad["ok"] and "tool_calls" in bad["missing"]


# --- model metadata -----------------------------------------------------------


def test_normalize_model_metadata_strips_urls() -> None:
    meta = normalize_model_metadata(
        {
            "provider": "openai-compatible",
            "model": "qwen-7b",
            "base_url": "http://localhost:8080/v1?token=secret",
            "temperature": 0.2,
            "reasoning_effort": "low",
        }
    )
    assert meta.base_url_host == "localhost"
    assert "token" not in (meta.base_url_host or "")
    assert meta.sampling["temperature"] == 0.2
    assert meta.fingerprint()


# --- retries --------------------------------------------------------------------


def test_retries_transient_then_success_records_attempts() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("transient")
        return "done"

    slept: list[float] = []
    out = run_with_retries(
        flaky,
        lambda e: "timeout",
        RetryPolicy(max_attempts=4, base_delay_s=0.01),
        sleeper=slept.append,
    )
    assert out["result"] == "done"
    assert len(out["attempts"]) == 3
    assert out["attempts"][0]["ok"] is False
    assert out["benchmark_waited_s"] > 0 and len(slept) == 2


def test_no_retry_for_permanent_errors() -> None:
    attempts = {"n": 0}

    def boom() -> None:
        attempts["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        run_with_retries(
            boom, lambda e: "permanent", RetryPolicy(max_attempts=3), sleeper=lambda s: None
        )
    assert attempts["n"] == 1


# --- health checks ----------------------------------------------------------------


def test_health_check_aggregates_probes() -> None:
    report = adapter_health_check("local", {"config": lambda: True, "endpoint": lambda: False})
    assert not report["healthy"]
    assert report["checks"]["config"] is True and report["checks"]["endpoint"] is False


# --- credentials ---------------------------------------------------------------------


def test_credential_resolver_never_leaks_value_in_ref(tmp_path: Path) -> None:
    kf = tmp_path / "secrets.env"
    kf.write_text("API_KEY=super-secret-value\x0a", encoding="utf-8")
    resolver = CredentialResolver(env={}, keyfile=str(kf))
    ref = resolver.resolve_ref("API_KEY")
    assert ref["present"] is True
    blob = json.dumps(ref)
    assert "super-secret-value" not in blob
    assert resolver.resolve_ref("MISSING")["present"] is False


# --- cost accounting -------------------------------------------------------------------

PRICE_JSON = json.dumps(
    {
        "prices": {
            "model-a": [
                {"input_per_1k": 0.5, "output_per_1k": 1.5, "effective_from": "2026-01-01"},
                {"input_per_1k": 0.4, "output_per_1k": 1.0, "effective_from": "2026-06-01"},
            ]
        }
    }
)


def test_cost_uses_newest_effective_price_or_fails_closed() -> None:
    table = PriceTable.load(PRICE_JSON)
    june = table.compute_cost("model-a", 1000, 1000, "2026-07-01")
    assert june["cost"] == pytest.approx(1.4)
    jan = table.compute_cost("model-a", 1000, 1000, "2026-02-01")
    assert jan["cost"] == pytest.approx(2.0)
    with pytest.raises(KeyError):
        table.compute_cost("unpriced-model", 1, 1, "2026-07-01")
    unknown = table.compute_cost("unpriced-model", 1, 1, "2026-07-01", allow_unpriced=True)
    assert unknown["cost"] is None and unknown["priced"] is False


# --- MCP ------------------------------------------------------------------------------


def test_mcp_conformance_against_fake_server() -> None:
    report = conformance_check(fake_server_command())
    assert report["ok"], report
    assert report["checks"]["initialize"]
    assert report["checks"]["tools_list"]
    assert report["checks"]["tools_call_echo"]
    assert report["checks"]["unknown_tool_errors"]


# --- experiment engine -------------------------------------------------------------------


def _runner(task_id: str, repetition: int) -> dict[str, object]:
    if task_id == "boom-task":
        raise RuntimeError("isolated crash")
    return {"task_id": task_id, "rep": repetition, "success": True}


def test_execute_experiment_resume_isolation_cancel(tmp_path: Path) -> None:
    manifest = ExperimentManifest(suite_id="s", agent_adapter="scripted").finalize()
    assert manifest.manifest_sha256
    state_path = tmp_path / "state.json"
    items = [("t1", 1), ("t2", 1), ("boom-task", 1)]
    state = execute_experiment(manifest, items, _runner, state_path, max_workers=2)
    assert state.status == "completed_with_failures"
    assert idempotent_key(manifest.experiment_id, "boom-task", 1) in state.failures
    assert len(state.completed) == 2

    # resume: completed items are not re-run
    ran: list[str] = []

    def counting_runner(task_id: str, repetition: int) -> dict[str, object]:
        ran.append(task_id)
        return {"task_id": task_id, "rep": repetition}

    state2 = execute_experiment(manifest, [("t1", 1)], counting_runner, state_path)
    assert ran == []  # nothing re-executed
    # cumulative experiment status still reflects the earlier isolated failure
    assert state2.status == "completed_with_failures"

    # graceful cancel before scheduling anything new
    state3 = execute_experiment(
        manifest, [("t9", 1)], counting_runner, state_path, cancelled=lambda: True
    )
    assert state3.status == "cancelled"


def test_sharding_roundtrip_merge(tmp_path: Path) -> None:
    items = [(f"task-{i}", 1) for i in range(7)]
    shards = shard_work_items(items, 3)
    assert sum(len(s) for s in shards) == 7
    paths = []
    for i, shard in enumerate(shards):
        sp = tmp_path / f"shard{i}.json"
        RunState(
            experiment_id="exp", completed={item[0]: {"task": item[0]} for item in shard}
        ).save(sp)
        paths.append(sp)
    merged = merge_run_states(paths, "exp")
    assert len(merged.completed) == 7


def test_coordinator_atomic_claim_and_priority(tmp_path: Path) -> None:
    coord = Coordinator(tmp_path / "queue")
    low = coord.enqueue({"task": "low"}, priority=9)
    high = coord.enqueue({"task": "high"}, priority=1)
    job = coord.claim_next("worker-a")
    assert job is not None and job["task"] == "high"
    assert coord.pending_count() == 1
    second = coord.claim_next("worker-b")
    assert second is not None and second["task"] == "low"
    assert coord.claim_next("worker-c") is None
    coord.submit_result(high, {"ok": True})
    assert (coord.results_dir / f"{high}.json").exists()
    assert low and high  # silence unused warnings


def test_worker_inventory_shape() -> None:
    inv = default_worker_inventory("w1")
    assert inv.worker_id == "w1"
    assert inv.max_concurrency >= 1
    assert inv.os_name
