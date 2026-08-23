"""Tests for self-hosted server foundations (RBAC, tokens, policy, approvals,
audit chain, quotas, webhooks, retention, HTTP API incl. SSE/metrics)."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest
from tooltrace.server.core import (
    STATE,
    ApprovalWorkflow,
    AuditLog,
    LocalDevAuthProvider,
    OIDCProviderHook,
    QuotaTracker,
    TokenStore,
    User,
    WebhookDispatcher,
    WorkspacePolicy,
    apply_retention,
    authorize,
    evaluate_policy,
    serve,
)


def make_user(role: str = "admin", ws: str = "ws1", uid: str = "alice") -> User:
    return User(user_id=uid, display_name=uid, role=role, workspace_id=ws)


# --- RBAC ------------------------------------------------------------------------

def test_rbac_roles_and_tenant_scoping() -> None:
    admin = make_user("admin")
    viewer = make_user("viewer")
    assert authorize(admin, "approve_privileged", "ws1")
    assert not authorize(viewer, "run_experiments", "ws1")
    outsider = make_user("admin", ws="ws2")
    assert not authorize(outsider, "read_results", "ws1")  # tenant isolation


# --- tokens -------------------------------------------------------------------------

def test_tokens_hashed_rotatable_and_verifiable() -> None:
    store = TokenStore()
    raw = store.issue("alice", "ws1", ["run_experiments"])
    assert raw.startswith("ttk_")
    info = store.verify(raw)
    assert info is not None and info["owner"] == "alice"
    new_raw = store.rotate(raw, "alice", "ws1", ["run_experiments"])
    assert new_raw is not None and new_raw != raw
    assert store.verify(raw) is None  # old token dead after rotation


# --- auth providers ---------------------------------------------------------------------

def test_local_dev_auth_and_oidc_hook() -> None:
    provider = LocalDevAuthProvider([make_user()])
    assert provider.authenticate("alice") is not None
    assert provider.authenticate("ghost") is None
    hook = OIDCProviderHook(verifier=lambda a: {"sub": "u1"})
    assert hook.exchange("assertion")["sub"] == "u1"
    with pytest.raises(RuntimeError):
        OIDCProviderHook().exchange("x")


# --- policy -------------------------------------------------------------------------------

def test_policy_as_code_blocks_disallowed_and_publication() -> None:
    policy = WorkspacePolicy(allowed_providers=["local"], network_modes=["offline"])
    out = evaluate_policy("run_experiment", {"provider": "openai", "network_mode": "offline"}, policy)
    assert not out["allowed"] and any("provider" in v for v in out["violations"])
    ok = evaluate_policy("run_experiment", {"provider": "local", "network_mode": "offline"}, policy)
    assert ok["allowed"]
    pub = evaluate_policy("publish_results", {}, WorkspacePolicy())
    assert not pub["allowed"]  # requires approval by default


# --- approvals --------------------------------------------------------------------------------

def test_approval_workflow_requires_admin_decision() -> None:
    wf = ApprovalWorkflow()
    requester = make_user("runner")
    req = wf.request("r1", "ws1", "publish_results", {}, requester)
    assert req.status == "pending"
    with pytest.raises(PermissionError):
        wf.decide("r1", requester, True)  # runner cannot decide
    decided = wf.decide("r1", make_user("admin"), True)
    assert decided.status == "approved" and decided.decided_by == "alice"


# --- audit chain ---------------------------------------------------------------------------------

def test_audit_log_hash_chain_detects_tampering(tmp_path: Path) -> None:
    log = AuditLog(path=tmp_path / "audit.jsonl")
    log.append("alice", "experiment.create", "e1")
    log.append("bob", "approval.decide", "a1")
    assert log.verify_chain()
    # tamper with an entry
    log._entries[0]["action"] = "forged"
    assert not log.verify_chain()


# --- quotas ------------------------------------------------------------------------------------------

def test_quota_tracker_enforces_limits() -> None:
    quota = QuotaTracker({"runs": 2})
    assert quota.consume("runs") and quota.consume("runs")
    assert not quota.consume("runs")
    assert quota.consume("unlimited_resource")


# --- webhooks -------------------------------------------------------------------------------------------

def test_webhooks_signed_with_retries() -> None:
    calls: list[tuple[str, bytes, dict[str, str]]] = []

    def flaky_poster(url: str, body: bytes, headers: dict[str, str]) -> int:
        calls.append((url, body, headers))
        return 500 if len(calls) < 3 else 200

    dispatcher = WebhookDispatcher(secret="s3cret", poster=flaky_poster)
    dispatcher.subscribe("https://hooks.example/tt", ["run.completed"])
    out = dispatcher.deliver("run.completed", {"run_id": "r9"})
    assert out["delivered"] is True and out["attempts"] == 3
    import hashlib
    import hmac as hmac_mod

    expected_sig = hmac_mod.new(b"s3cret", calls[0][1], hashlib.sha256).hexdigest()
    assert calls[0][2]["X-ToolTrace-Signature"] == expected_sig


# --- retention ----------------------------------------------------------------------------------------------

def test_retention_respects_legal_hold() -> None:
    now = time.time()
    records = [
        {"id": "old", "created_at_epoch": now - 100 * 86400},
        {"id": "held", "created_at_epoch": now - 100 * 86400},
        {"id": "new", "created_at_epoch": now},
    ]
    keep, deleted = apply_retention(records, max_age_days=90, now_epoch=now, legal_hold_ids={"held"})
    assert deleted == ["old"]
    assert {r["id"] for r in keep} == {"held", "new"}


# --- HTTP API ----------------------------------------------------------------------------------------------------

@pytest.fixture()
def server() -> object:
    STATE.users.clear()
    STATE.experiments.clear()
    STATE.events.clear()
    STATE.metrics_counters.update({"runs_started": 0, "runs_completed": 0, "runs_failed": 0})
    alice = make_user("admin")
    bob = make_user("viewer", uid="bob")
    STATE.users.update({"alice": alice, "bob": bob})
    token = STATE.tokens.issue("alice", "ws1", ["run_experiments"])
    STATE.quotas["ws1"] = QuotaTracker({"runs": 1})
    srv = serve(port=0)
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", token
    srv.shutdown()


def _post(base: str, path: str, token: str | None, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, json.loads(e.read())


def _get(base: str, path: str, token: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, e.read()


def test_http_health_ready_metrics(server: object) -> None:
    base, _ = server
    status, body = _get(base, "/healthz")
    assert status == 200 and json.loads(body)["status"] == "ok"
    status, body = _get(base, "/readyz")
    assert status == 200 and json.loads(body)["ready"] is True
    status, body = _get(base, "/metrics")
    text = json.loads(body)["_text"]
    assert "tooltrace_uptime_seconds" in text and "tooltrace_runs_started" in text


def test_http_experiment_rbac_quota_audit(server: object) -> None:
    base, token = server
    # no auth -> forbidden
    status, _ = _post(base, "/api/v1/experiments", None, {"workspace_id": "ws1"})
    assert status == 403
    # authorized create
    status, body = _post(base, "/api/v1/experiments", token, {"workspace_id": "ws1", "suite": "smoke"})
    assert status == 201 and body["status"] == "queued"
    exp_id = str(body["id"])
    assert STATE.audit.verify_chain()
    # quota exhausted -> 429
    status, body = _post(base, "/api/v1/experiments", token, {"workspace_id": "ws1"})
    assert status == 429
    # tenant scoping on list
    status, body_bytes = _get(base, "/api/v1/experiments", token)
    listed = json.loads(body_bytes)["experiments"]
    assert len(listed) == 1 and listed[0]["id"] == exp_id


def test_http_approval_flow(server: object) -> None:
    base, token = server
    status, body = _post(base, "/api/v1/approvals", token, {"workspace_id": "ws1", "action": "publish_results"})
    assert status == 201
    apr_id = body["request_id"]
    status, body = _post(base, f"/api/v1/approvals/{apr_id}/decide", token, {"approve": True})
    assert status == 200 and body["status"] == "approved"


def test_http_sse_stream(server: object) -> None:
    base, _token = server
    STATE.events.append({"type": "experiment.queued", "id": "exp-x", "at": "now"})
    status, raw = _get(base, "/api/v1/events")
    assert status == 200
    text = raw.decode("utf-8")
    assert "data:" in text
    assert "experiment.queued" in text
