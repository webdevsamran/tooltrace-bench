"""Self-hosted team/enterprise server foundations (features 105-122).

Pure-logic services plus a dependency-free HTTP API (stdlib ``http.server``):

- organizations/workspaces/projects with strict tenant scoping;
- users/teams/service accounts and RBAC (viewer/runner/task_author/reviewer/
  admin/service_account);
- local-dev auth provider + OIDC/SAML abstraction hooks;
- API tokens: scoped permissions, rotation metadata, hashed storage;
- policy-as-code for providers/models/tools/packs/network/budgets/publication;
- approval workflows for privileged operations;
- immutable hash-chained audit events;
- quotas per workspace (runs/concurrency/tokens/money);
- signed webhooks (HMAC-SHA256) with retry policy;
- retention/deletion controls;
- REST endpoints incl. SSE progress stream, /metrics (Prometheus text),
  /healthz, /readyz and /openapi.json.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from tooltrace.tasks.governance import utc_now_iso

# ---------------------------------------------------------------------------
# RBAC (features 105, 106, 108)
# ---------------------------------------------------------------------------

ROLES = ("viewer", "runner", "task_author", "reviewer", "admin", "service_account")
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"read_public", "read_results"}),
    "runner": frozenset({"read_public", "read_results", "run_experiments"}),
    "task_author": frozenset({"read_public", "read_results", "run_experiments", "author_tasks"}),
    "reviewer": frozenset({"read_public", "read_results", "run_experiments", "author_tasks", "review_publication"}),
    "admin": frozenset(
        {"read_public", "read_results", "run_experiments", "author_tasks", "review_publication",
         "manage_members", "manage_policies", "manage_budgets", "approve_privileged"}
    ),
    "service_account": frozenset({"read_results", "run_experiments"}),
}


@dataclass
class User:
    user_id: str
    display_name: str
    role: str
    workspace_id: str
    email: str | None = None


class TokenStore:
    """API tokens stored hashed (sha256); rotation metadata kept; raw token is
    shown exactly once at creation."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, Any]] = {}

    def issue(self, owner: str, workspace_id: str, scopes: list[str], ttl_days: int = 90) -> str:
        raw = "ttk_" + secrets.token_urlsafe(24)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self._hashes[digest] = {
            "owner": owner,
            "workspace_id": workspace_id,
            "scopes": scopes,
            "issued_at": utc_now_iso(),
            "expires_hint_days": ttl_days,
            "rotated_from": None,
        }
        return raw

    def rotate(self, raw_token: str, owner: str, workspace_id: str, scopes: list[str]) -> str | None:
        old = hashlib.sha256(raw_token.encode()).hexdigest()
        if old not in self._hashes:
            return None
        new_raw = self.issue(owner, workspace_id, scopes)
        digest = hashlib.sha256(new_raw.encode()).hexdigest()
        self._hashes[digest]["rotated_from"] = old[:12]
        del self._hashes[old]
        return new_raw

    def verify(self, raw_token: str) -> dict[str, Any] | None:
        return self._hashes.get(hashlib.sha256(raw_token.encode()).hexdigest())


def authorize(user: User, permission: str, workspace_id: str) -> bool:
    """Tenant-scoped authorization: role permissions AND same workspace."""
    if user.workspace_id != workspace_id:
        return False
    return permission in ROLE_PERMISSIONS.get(user.role, frozenset())


# ---------------------------------------------------------------------------
# Auth providers (feature 107)
# ---------------------------------------------------------------------------


class LocalDevAuthProvider:
    """Deterministic local-development auth: username -> User, no passwords."""

    def __init__(self, users: list[User]) -> None:
        self._users = {u.user_id: u for u in users}

    def authenticate(self, username: str) -> User | None:
        return self._users.get(username)


class OIDCProviderHook:
    """Abstraction hook for OIDC/SAML IdPs. Verifies an externally supplied
    assertion callback; never implements crypto itself."""

    def __init__(self, verifier: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._verifier = verifier

    def exchange(self, assertion: str) -> dict[str, Any]:
        if self._verifier is None:
            raise RuntimeError("no OIDC verifier configured; configure one for SSO deployments")
        return self._verifier(assertion)


# ---------------------------------------------------------------------------
# Policy-as-code (feature 109)
# ---------------------------------------------------------------------------


class WorkspacePolicy(BaseModel):
    allowed_providers: list[str] = Field(default_factory=lambda: ["*"])
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    allowed_task_packs: list[str] = Field(default_factory=lambda: ["*"])
    network_modes: list[str] = Field(default_factory=lambda: ["offline"])
    max_runs_per_day: int = 1000
    publication_requires_approval: bool = True


def evaluate_policy(action: str, payload: dict[str, Any], policy: WorkspacePolicy) -> dict[str, Any]:
    violations: list[str] = []
    if action == "run_experiment":
        if payload.get("provider") not in policy.allowed_providers and "*" not in policy.allowed_providers:
            violations.append("provider not allowed by policy")
        if payload.get("model") not in policy.allowed_models and "*" not in policy.allowed_models:
            violations.append("model not allowed by policy")
        if payload.get("network_mode") not in policy.network_modes:
            violations.append("network mode not allowed by policy")
        pack = payload.get("task_pack")
        if pack and pack not in policy.allowed_task_packs and "*" not in policy.allowed_task_packs:
            violations.append("task pack not allowed by policy")
    elif action == "publish_results" and policy.publication_requires_approval:
        violations.append("publication requires reviewer approval")
    return {"allowed": not violations, "violations": violations}


# ---------------------------------------------------------------------------
# Approvals (feature 110)
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    request_id: str
    workspace_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | approved | rejected
    requested_by: str = ""
    decided_by: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ApprovalWorkflow:
    def __init__(self) -> None:
        self.requests: dict[str, ApprovalRequest] = {}

    def request(self, request_id: str, workspace_id: str, action: str, payload: dict[str, Any], requester: User) -> ApprovalRequest:
        req = ApprovalRequest(request_id=request_id, workspace_id=workspace_id, action=action, payload=payload, requested_by=requester.user_id)
        self.requests[request_id] = req
        return req

    def decide(self, request_id: str, decider: User, approve: bool) -> ApprovalRequest:
        req = self.requests[request_id]
        if not authorize(decider, "approve_privileged", req.workspace_id):
            raise PermissionError("only admins may decide approval requests")
        req.status = "approved" if approve else "rejected"
        req.decided_by = decider.user_id
        return req


# ---------------------------------------------------------------------------
# Immutable audit log (feature 111) - hash chained
# ---------------------------------------------------------------------------


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._entries: list[dict[str, Any]] = []
        self._prev_hash = "genesis"

    def append(self, actor: str, action: str, target: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "seq": len(self._entries),
            "timestamp": utc_now_iso(),
            "actor": actor,
            "action": action,
            "target": target,
            "details": details or {},
            "prev_hash": self._prev_hash,
        }
        entry["entry_hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        self._entries.append(entry)
        self._prev_hash = entry["entry_hash"]
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + chr(10))
        return entry

    def verify_chain(self) -> bool:
        prev = "genesis"
        for e in self._entries:
            payload = {k: v for k, v in e.items() if k != "entry_hash"}
            if e["prev_hash"] != prev or e["entry_hash"] != hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest():
                return False
            prev = e["entry_hash"]
        return True


# ---------------------------------------------------------------------------
# Quotas (feature 114)
# ---------------------------------------------------------------------------


class QuotaTracker:
    def __init__(self, limits: dict[str, int]) -> None:
        self.limits = limits
        self.used: dict[str, int] = dict.fromkeys(limits, 0)

    def consume(self, resource: str, amount: int = 1) -> bool:
        limit = self.limits.get(resource)
        if limit is None:
            return True
        if self.used[resource] + amount > limit:
            return False
        self.used[resource] += amount
        return True


# ---------------------------------------------------------------------------
# Signed webhooks (feature 115)
# ---------------------------------------------------------------------------


class WebhookDispatcher:
    def __init__(self, secret: str, poster: Callable[[str, bytes, dict[str, str]], int]) -> None:
        self.secret = secret.encode()
        self._poster = poster
        self.subscriptions: list[dict[str, Any]] = []

    def subscribe(self, url: str, events: list[str]) -> None:
        self.subscriptions.append({"url": url, "events": events})

    def sign(self, body: bytes) -> str:
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def deliver(self, event: str, payload: dict[str, Any], max_retries: int = 3) -> dict[str, Any]:
        body = json.dumps({"event": event, "payload": payload}).encode()
        headers = {"Content-Type": "application/json", "X-ToolTrace-Signature": self.sign(body)}
        attempts = 0
        last_status = 0
        for sub in self.subscriptions:
            if event not in sub["events"]:
                continue
            for _attempt in range(max_retries):
                attempts += 1
                last_status = self._poster(sub["url"], body, headers)
                if 200 <= last_status < 300:
                    break
        return {"event": event, "delivered": 200 <= last_status < 300, "attempts": attempts, "last_status": last_status}


# ---------------------------------------------------------------------------
# Retention (feature 112)
# ---------------------------------------------------------------------------


def apply_retention(records: list[dict[str, Any]], max_age_days: int, now_epoch: float, legal_hold_ids: set[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Delete records older than retention unless under legal-hold-style hold."""
    hold = legal_hold_ids or set()
    cutoff = now_epoch - max_age_days * 86400
    keep: list[dict[str, Any]] = []
    deleted: list[str] = []
    for r in records:
        age = r.get("created_at_epoch", now_epoch)
        rid = str(r.get("id"))
        if age < cutoff and rid not in hold:
            deleted.append(rid)
        else:
            keep.append(r)
    return keep, deleted


# ---------------------------------------------------------------------------
# HTTP API (features 117, 118, 119, 120) - stdlib only
# ---------------------------------------------------------------------------


class ServerState:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.tokens = TokenStore()
        self.audit = AuditLog()
        self.approvals = ApprovalWorkflow()
        self.policies: dict[str, WorkspacePolicy] = {}
        self.quotas: dict[str, QuotaTracker] = {}
        self.experiments: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []  # for SSE
        self.metrics_counters: dict[str, int] = {"runs_started": 0, "runs_completed": 0, "runs_failed": 0}
        self.started_at = time.time()


STATE = ServerState()


def _token_user(raw_token: str) -> User | None:
    info = STATE.tokens.verify(raw_token)
    if info is None:
        return None
    return STATE.users.get(info["owner"])


ROUTES: dict[tuple[str, str], Callable[[dict[str, Any], User | None], tuple[int, dict[str, Any]]]] = {}


def route(method: str, path: str) -> Callable[..., Any]:
    def register(fn: Callable[[dict[str, Any], User | None], tuple[int, dict[str, Any]]]) -> Callable[..., Any]:
        ROUTES[(method, path)] = fn
        return fn

    return register


@route("GET", "/healthz")
def _healthz(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    return 200, {"status": "ok"}


@route("GET", "/readyz")
def _readyz(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    ready = bool(STATE.users) and STATE.audit.verify_chain()
    return (200, {"ready": True}) if ready else (503, {"ready": False})


@route("GET", "/metrics")
def _metrics(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    uptime = round(time.time() - STATE.started_at, 1)
    lines = [f'tooltrace_uptime_seconds {uptime}']
    for name, value in STATE.metrics_counters.items():
        lines.append(f"tooltrace_{name} {value}")
    lines.append(f"tooltrace_queue_depth {len(STATE.experiments)}")
    return 200, {"_text": chr(10).join(lines) + chr(10)}

@route("POST", "/api/v1/experiments")
def _create_experiment(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None or not authorize(user, "run_experiments", str(body.get("workspace_id", ""))):
        return 403, {"error": "forbidden"}
    quota = STATE.quotas.get(str(body.get("workspace_id")))
    if quota is not None and not quota.consume("runs"):
        return 429, {"error": "quota exceeded"}
    exp_id = "exp-" + secrets.token_hex(6)
    STATE.experiments[exp_id] = {"id": exp_id, "status": "queued", **body}
    STATE.metrics_counters["runs_started"] += 1
    STATE.events.append({"type": "experiment.queued", "id": exp_id, "at": utc_now_iso()})
    STATE.audit.append(actor=user.user_id, action="experiment.create", target=exp_id)
    return 201, {"id": exp_id, "status": "queued"}


@route("GET", "/api/v1/experiments")
def _list_experiments(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    visible = [e for e in STATE.experiments.values() if e.get("workspace_id") == user.workspace_id]
    return 200, {"experiments": visible}


@route("POST", "/api/v1/approvals")
def _request_approval(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    req = STATE.approvals.request(
        request_id="apr-" + secrets.token_hex(5),
        workspace_id=str(body["workspace_id"]),
        action=str(body["action"]),
        payload=body.get("payload", {}),
        requester=user,
    )
    STATE.audit.append(actor=user.user_id, action="approval.request", target=req.request_id)
    return 201, req.model_dump(mode="json")


@route("POST", "/api/v1/approvals/{id}/decide")
def _decide_approval(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    try:
        req = STATE.approvals.decide(str(body.get("_path_id")), user, bool(body.get("approve")))
    except PermissionError:
        return 403, {"error": "forbidden"}
    except KeyError:
        return 404, {"error": "not found"}
    STATE.audit.append(actor=user.user_id, action="approval.decide", target=req.request_id, details={"approved": body.get("approve")})
    return 200, req.model_dump(mode="json")


OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "ToolTrace Bench Self-hosted API", "version": "1.0.0"},
    "paths": {
        "/healthz": {"get": {"summary": "Liveness"}},
        "/readyz": {"get": {"summary": "Readiness"}},
        "/metrics": {"get": {"summary": "Prometheus-compatible metrics"}},
        "/api/v1/experiments": {
            "get": {"summary": "List experiments in caller workspace"},
            "post": {"summary": "Create experiment (RBAC + quota enforced)"},
        },
        "/api/v1/approvals": {"post": {"summary": "Request privileged-action approval"}},
        "/api/v1/events": {"get": {"summary": "SSE event stream"}},
    },
}


def make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # quiet tests
            pass

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:  # request body size limit
                self._send_json(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return
            path = self.path.split("?")[0]
            auth = self.headers.get("Authorization", "")
            user = _token_user(auth.removeprefix("Bearer ").strip()) if auth.startswith("Bearer ") else None
            # dynamic segment: /api/v1/approvals/{id}/decide
            key = (method, path)
            if key not in ROUTES and path.endswith("/decide"):
                parts = path.rstrip("/").split("/")
                if len(parts) == 6 and parts[3] == "approvals" and parts[5] == "decide":
                    body["_path_id"] = parts[4]
                    key = (method, "/api/v1/approvals/{id}/decide")
            handler = ROUTES.get(key)
            if handler is None:
                self._send_json(404, {"error": "not found"})
                return
            status, payload = handler(body, user)
            self._send_json(status, payload)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path.startswith("/api/v1/events"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for event in list(STATE.events)[-10:]:
                        chunk = ("data: " + json.dumps(event) + chr(10) + chr(10)).encode()
                        self.wfile.write(chunk)
                    self.wfile.write(b"data: end-of-snapshot\x0a\x0a")
                except OSError:
                    pass
                return
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8737) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
