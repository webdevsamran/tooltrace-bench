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
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from tooltrace.tasks.governance import utc_now_iso

# ---------------------------------------------------------------------------
# RBAC (features 105, 106, 108)
# ---------------------------------------------------------------------------

ROLES = (
    "viewer",
    "auditor",
    "runner",
    "task_author",
    "reviewer",
    "admin",
    "service_account",
)
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"read_public", "read_results"}),
    # Read-only like a viewer, and a separate role rather than a reuse of one.
    # An auditor's grant is time-boxed and watermarked, and both of those are
    # properties of the *grant*; keeping the role distinct is what lets a
    # response say which it is, and what lets an access log answer "who saw
    # this, under whose authority, and when did that end".
    "auditor": frozenset({"read_public", "read_results", "read_evidence"}),
    "runner": frozenset({"read_public", "read_results", "run_experiments"}),
    "task_author": frozenset({"read_public", "read_results", "run_experiments", "author_tasks"}),
    "reviewer": frozenset(
        {"read_public", "read_results", "run_experiments", "author_tasks", "review_publication"}
    ),
    "admin": frozenset(
        {
            "read_public",
            "read_results",
            "read_evidence",
            "run_experiments",
            "author_tasks",
            "review_publication",
            "manage_members",
            "manage_policies",
            "manage_budgets",
            "approve_privileged",
        }
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
    shown exactly once at creation.

    **Expiry is enforced, not hinted.** This stored `expires_hint_days` and
    `verify` returned the record whatever its age, so every token this server
    ever issued was permanent. That is a defect rather than an unwired field: a
    time-boxed grant that never ends is the opposite of what the caller asked
    for, and an auditor link is the case where it matters most.

    The clock is injectable so an expiry can be tested without waiting a day
    and without a test that passes only until it does not.
    """

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._hashes: dict[str, dict[str, Any]] = {}
        self._now = now or (lambda: datetime.now(UTC))

    def issue(
        self,
        owner: str,
        workspace_id: str,
        scopes: list[str],
        ttl_days: int = 90,
        *,
        watermark: str | None = None,
    ) -> str:
        raw = "ttk_" + secrets.token_urlsafe(24)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        issued = self._now()
        self._hashes[digest] = {
            "owner": owner,
            "workspace_id": workspace_id,
            "scopes": scopes,
            "issued_at": issued.isoformat(),
            # An absolute instant, not a duration. A duration has to be added to
            # something at read time, and the something is what gets forgotten.
            "expires_at": (issued + timedelta(days=ttl_days)).isoformat(),
            "ttl_days": ttl_days,
            # Travels with the token so every response served under it can say
            # who it was issued to. A watermark applied at render time is a
            # watermark somebody can render without.
            "watermark": watermark,
            "rotated_from": None,
        }
        return raw

    def rotate(
        self, raw_token: str, owner: str, workspace_id: str, scopes: list[str]
    ) -> str | None:
        old = hashlib.sha256(raw_token.encode()).hexdigest()
        if old not in self._hashes:
            return None
        previous = self._hashes[old]
        # The watermark survives rotation. Losing it would turn a watermarked
        # auditor grant into an anonymous one by rotating it, which is the one
        # operation an auditor can perform on their own token.
        new_raw = self.issue(
            owner,
            workspace_id,
            scopes,
            ttl_days=int(previous.get("ttl_days", 90)),
            watermark=previous.get("watermark"),
        )
        digest = hashlib.sha256(new_raw.encode()).hexdigest()
        self._hashes[digest]["rotated_from"] = old[:12]
        del self._hashes[old]
        return new_raw

    def verify(self, raw_token: str) -> dict[str, Any] | None:
        """The token's record, or None when it is unknown **or expired**."""
        record = self._hashes.get(hashlib.sha256(raw_token.encode()).hexdigest())
        if record is None:
            return None
        if self.expired(record):
            return None
        return record

    def expired(self, record: dict[str, Any]) -> bool:
        raw = record.get("expires_at")
        if not isinstance(raw, str) or not raw:
            # A record without an expiry predates enforcement. Treated as live
            # rather than dead: silently revoking every existing token would be
            # a worse failure than the one being fixed.
            return False
        try:
            expires = datetime.fromisoformat(raw)
        except ValueError:
            return False
        return self._now() >= expires


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


def evaluate_policy(
    action: str, payload: dict[str, Any], policy: WorkspacePolicy
) -> dict[str, Any]:
    violations: list[str] = []
    if action == "run_experiment":
        if (
            payload.get("provider") not in policy.allowed_providers
            and "*" not in policy.allowed_providers
        ):
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

    def request(
        self,
        request_id: str,
        workspace_id: str,
        action: str,
        payload: dict[str, Any],
        requester: User,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            request_id=request_id,
            workspace_id=workspace_id,
            action=action,
            payload=payload,
            requested_by=requester.user_id,
        )
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

    def append(
        self, actor: str, action: str, target: str, details: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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

    def entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Newest first. A copy, so a caller cannot rewrite the chain by
        mutating what it was handed."""
        rows = [dict(e) for e in reversed(self._entries)]
        return rows[:limit] if limit else rows

    def restore(self, entries: list[dict[str, Any]]) -> None:
        """Replace the chain from a snapshot, oldest first.

        `_prev_hash` is set from the last entry so an append after a restore
        continues the chain rather than starting a second one that verifies on
        its own and not against what came before.
        """
        self._entries = [dict(e) for e in entries]
        self._prev_hash = self._entries[-1]["entry_hash"] if self._entries else "genesis"

    def verify_chain(self) -> bool:
        prev = "genesis"
        for e in self._entries:
            payload = {k: v for k, v in e.items() if k != "entry_hash"}
            if (
                e["prev_hash"] != prev
                or e["entry_hash"]
                != hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            ):
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
        return {
            "event": event,
            "delivered": 200 <= last_status < 300,
            "attempts": attempts,
            "last_status": last_status,
        }


# ---------------------------------------------------------------------------
# Retention (feature 112)
# ---------------------------------------------------------------------------


def apply_retention(
    records: list[dict[str, Any]],
    max_age_days: int,
    now_epoch: float,
    legal_hold_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
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
        # Held here rather than constructed per-call so its subscriptions are
        # addressable: `GET /api/v1/webhooks` cannot list what it cannot reach,
        # and the console showed invented rows for exactly that reason.
        self.webhooks: WebhookDispatcher | None = None
        self.events: list[dict[str, Any]] = []  # for SSE
        self.metrics_counters: dict[str, int] = {
            "runs_started": 0,
            "runs_completed": 0,
            "runs_failed": 0,
        }
        self.started_at = time.time()


STATE = ServerState()


def _token_user(raw_token: str) -> User | None:
    info = STATE.tokens.verify(raw_token)
    if info is None:
        return None
    return STATE.users.get(info["owner"])


def _token_watermark(raw_token: str | None) -> str | None:
    """The watermark on the grant a request arrived under, if any."""
    if not raw_token:
        return None
    info = STATE.tokens.verify(raw_token)
    return str(info["watermark"]) if info and info.get("watermark") else None


def auditor_grant(
    store: TokenStore,
    users: dict[str, User],
    *,
    auditor_name: str,
    workspace_id: str,
    issued_by: str,
    ttl_days: int = 14,
) -> dict[str, Any]:
    """A read-only, time-boxed, watermarked grant for an external reviewer.

    Three properties, and each exists because of how this normally goes wrong.

    **Read-only** by role rather than by convention: an auditor holds no
    permission that writes, so a mistake cannot become a change to the thing
    under review.

    **Time-boxed** by an absolute instant the store enforces. A grant "for the
    duration of the audit" that outlives it is how a temporary reviewer becomes
    a permanent one, and this store previously stored the duration as a *hint*
    and honoured it never.

    **Watermarked** with who it was issued to, by whom, and when. It rides on
    the token, so every response served under it can carry it -- a watermark
    applied at render time is one somebody can render without.

    The raw token is returned exactly once, like every other token here.
    """
    user_id = f"auditor:{auditor_name}"
    watermark = (
        f"Issued to {auditor_name} by {issued_by} on {utc_now_iso()}; expires in {ttl_days}d"
    )
    users[user_id] = User(
        user_id=user_id,
        display_name=f"{auditor_name} (auditor)",
        role="auditor",
        workspace_id=workspace_id,
    )
    raw = store.issue(
        owner=user_id,
        workspace_id=workspace_id,
        scopes=sorted(ROLE_PERMISSIONS["auditor"]),
        ttl_days=ttl_days,
        watermark=watermark,
    )
    record = store.verify(raw)
    assert record is not None  # just issued
    return {
        "token": raw,
        "user_id": user_id,
        "role": "auditor",
        "scopes": record["scopes"],
        "issued_at": record["issued_at"],
        "expires_at": record["expires_at"],
        "watermark": watermark,
        "statement": (
            f"Read-only access for {auditor_name}, expiring {record['expires_at']}. "
            "The token is shown once. Every response served under it carries the "
            "watermark above, and the grant stops working at that instant rather "
            "than relying on anyone to revoke it."
        ),
    }


ROUTES: dict[
    tuple[str, str], Callable[[dict[str, Any], User | None], tuple[int, dict[str, Any]]]
] = {}


def route(method: str, path: str) -> Callable[..., Any]:
    def register(
        fn: Callable[[dict[str, Any], User | None], tuple[int, dict[str, Any]]],
    ) -> Callable[..., Any]:
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
    lines = [f"tooltrace_uptime_seconds {uptime}"]
    for name, value in STATE.metrics_counters.items():
        lines.append(f"tooltrace_{name} {value}")
    lines.append(f"tooltrace_queue_depth {len(STATE.experiments)}")
    return 200, {"_text": chr(10).join(lines) + chr(10)}


@route("POST", "/api/v1/experiments")
def _create_experiment(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None or not authorize(user, "run_experiments", str(body.get("workspace_id", ""))):
        return 403, {"error": "forbidden"}
    workspace_id = str(body.get("workspace_id", ""))

    # Policy is evaluated here, before anything is queued.
    #
    # `evaluate_policy` was written, tested, and called by nothing -- so a
    # workspace could declare allowed providers, allowed models, allowed task
    # packs and permitted network modes, and the server would queue a run that
    # violated every one of them. The console described those settings as
    # governing what a workspace may do; they governed nothing.
    #
    # Before the quota, deliberately: a run the policy forbids should not consume
    # the budget it was never allowed to spend.
    policy = STATE.policies.get(workspace_id)
    if policy is not None:
        verdict = evaluate_policy("run_experiment", body, policy)
        if not verdict["allowed"]:
            STATE.audit.append(
                actor=user.user_id,
                action="experiment.denied",
                target=workspace_id,
                details={"violations": verdict["violations"]},
            )
            return 403, {"error": "policy violation", "violations": verdict["violations"]}

    quota = STATE.quotas.get(workspace_id)
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
    STATE.audit.append(
        actor=user.user_id,
        action="approval.decide",
        target=req.request_id,
        details={"approved": body.get("approve")},
    )
    return 200, req.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Read endpoints for the team console.
#
# Every one of these existed as server state with no way to ask for it, and the
# dashboard filled the gap with `DEMO_*` fixtures that it rendered *whether or
# not a server was connected* -- a connected administrator saw an invented user
# list, an invented approval queue and three invented workers with invented
# utilisation. `web/src/pages/workspace/shared.tsx` opens with the comment "demo
# rows never leak into data". They leaked.
#
# Where the server genuinely holds nothing -- there is no baseline store in this
# process, for instance -- the endpoint says so rather than inventing a row. An
# empty list with a reason is an answer; a fabricated one is not.
# ---------------------------------------------------------------------------


@route("GET", "/api/v1/users")
def _list_users(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    # Scoped to the caller's workspace, like experiments: a viewer in one
    # workspace has no business enumerating another's members.
    visible = [
        {
            "user_id": u.user_id,
            "display_name": u.display_name,
            "role": u.role,
            "workspace_id": u.workspace_id,
            "kind": "service_account" if u.role == "service_account" else "user",
        }
        for u in STATE.users.values()
        if u.workspace_id == user.workspace_id
    ]
    return 200, {"users": sorted(visible, key=lambda r: r["user_id"])}


@route("GET", "/api/v1/approvals")
def _list_approvals(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    visible = [
        r.model_dump(mode="json")
        for r in STATE.approvals.requests.values()
        if r.workspace_id == user.workspace_id
    ]
    return 200, {"approvals": sorted(visible, key=lambda r: str(r.get("request_id")))}


@route("GET", "/api/v1/audit")
def _list_audit(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    """The chain, and whether it still verifies.

    The verdict travels with the rows. An audit view that showed entries
    without saying whether the chain is intact is a list of claims, and the
    hash chain is the only reason to prefer it to a text file.
    """
    if user is None:
        return 401, {"error": "unauthorized"}
    # `read_evidence`, which auditor and admin carry: the audit chain is the
    # evidence, and a viewer has no business enumerating who did what.
    if not authorize(user, "read_evidence", user.workspace_id):
        return 403, {"error": "forbidden"}
    limit = int(body.get("limit") or 200)
    return 200, {
        "entries": STATE.audit.entries(limit=limit),
        "chain_verified": STATE.audit.verify_chain(),
        "limit": limit,
    }


@route("GET", "/api/v1/policies")
def _list_policies(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    policy = STATE.policies.get(user.workspace_id)
    quota = STATE.quotas.get(user.workspace_id)
    return 200, {
        "workspace_id": user.workspace_id,
        "policy": policy.model_dump(mode="json") if policy else None,
        "quota": (
            {"limits": dict(quota.limits), "used": dict(quota.used)} if quota is not None else None
        ),
    }


@route("GET", "/api/v1/webhooks")
def _list_webhooks(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    """Subscriptions, never the signing secret.

    The secret is what makes a delivery verifiable; putting it in a read
    endpoint would hand every viewer the ability to forge one.
    """
    if user is None:
        return 401, {"error": "unauthorized"}
    dispatcher = STATE.webhooks
    if dispatcher is None:
        return 200, {
            "webhooks": [],
            "configured": False,
            "note": "no webhook dispatcher is configured on this server",
        }
    return 200, {
        "webhooks": [
            {"url": sub["url"], "events": list(sub["events"])} for sub in dispatcher.subscriptions
        ],
        "configured": True,
    }


@route("GET", "/api/v1/workers")
def _list_workers(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    """This server's own node, measured -- not a fleet it does not coordinate.

    `tooltrace fleet` coordinates workers through a shared directory, not
    through this process, so a server asked for "the workers" can honestly
    report exactly one: itself. Reporting a fleet it has no connection to would
    be the invented data this endpoint exists to remove.
    """
    if user is None:
        return 401, {"error": "unauthorized"}
    from tooltrace.executors.experiment import default_worker_inventory

    node = default_worker_inventory("server")
    return 200, {
        "workers": [node.model_dump(mode="json")],
        "note": (
            "this server's own node. Fleet workers enrol through a shared queue "
            "(`tooltrace fleet work`) and are not registered with this process"
        ),
    }


@route("GET", "/api/v1/baselines")
def _list_baselines(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    """The registry `tooltrace baseline` writes, read from where it writes it."""
    if user is None:
        return 401, {"error": "unauthorized"}
    registry_path = Path(".tooltrace-baselines.json")
    if not registry_path.is_file():
        return 200, {
            "baselines": [],
            "note": "no .tooltrace-baselines.json in this server's working directory",
        }
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return 200, {"baselines": [], "note": f"baseline registry unreadable: {exc}"}
    return 200, {
        "baselines": [
            {"name": name, "bundle": str(bundle)} for name, bundle in sorted(registry.items())
        ]
    }


#: What a snapshot is compatible with. A restore is a destructive operation and
#: this is the only thing standing between "restored" and "silently half
#: restored" when the state shape changes between releases.
SNAPSHOT_VERSION = 1


def export_state() -> dict[str, Any]:
    """Everything this process holds that is worth keeping.

    The console's settings page has always told operators that "self-hosted
    metadata and artifact references support backup/restore", and pointed at a
    documentation anchor that did not exist, for a feature
    `docs/feature-status.md` graded **N: no backup or restore code ships**. One
    of those two statements had to go; this is the other way of resolving it.

    Artifacts are not in here. They are `.tooltrace` bundles on a filesystem,
    they are checksummed, and a backup tool that copied gigabytes of them into a
    JSON document would be a worse `cp`. What this captures is the part that
    only exists in memory.
    """
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "exported_at": utc_now_iso(),
        "users": {
            uid: {
                "user_id": u.user_id,
                "display_name": u.display_name,
                "role": u.role,
                "workspace_id": u.workspace_id,
            }
            for uid, u in STATE.users.items()
        },
        "policies": {ws: p.model_dump(mode="json") for ws, p in STATE.policies.items()},
        "quotas": {
            ws: {"limits": dict(q.limits), "used": dict(q.used)} for ws, q in STATE.quotas.items()
        },
        "approvals": {
            rid: r.model_dump(mode="json") for rid, r in STATE.approvals.requests.items()
        },
        "experiments": dict(STATE.experiments),
        "audit": STATE.audit.entries(),
        "metrics_counters": dict(STATE.metrics_counters),
    }


class SnapshotError(ValueError):
    """A snapshot this process will not restore, and why."""


def import_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Replace this process's state with a snapshot. Destructive, on purpose.

    Merging would be worse: a restore that left yesterday's deleted user in
    place is not a restore, and an operator who asked for one would have no way
    to tell. So it replaces, and refuses a snapshot it does not understand
    rather than restoring the half it recognises.

    The audit chain is restored and then **re-verified**. A backup that quietly
    accepted a tampered chain would launder exactly the evidence the chain
    exists to protect.
    """
    version = snapshot.get("snapshot_version")
    if version != SNAPSHOT_VERSION:
        raise SnapshotError(
            f"snapshot_version {version!r}, but this server restores {SNAPSHOT_VERSION}"
        )
    for required in ("users", "policies", "approvals", "experiments", "audit"):
        if required not in snapshot:
            raise SnapshotError(f"snapshot has no {required!r} section")

    STATE.users.clear()
    for uid, row in dict(snapshot["users"]).items():
        STATE.users[uid] = User(
            user_id=str(row["user_id"]),
            display_name=str(row["display_name"]),
            role=str(row["role"]),
            workspace_id=str(row["workspace_id"]),
        )

    STATE.policies.clear()
    for ws, row in dict(snapshot["policies"]).items():
        STATE.policies[ws] = WorkspacePolicy.model_validate(row)

    STATE.quotas.clear()
    for ws, row in dict(snapshot.get("quotas") or {}).items():
        tracker = QuotaTracker(dict(row.get("limits") or {}))
        tracker.used.update(dict(row.get("used") or {}))
        STATE.quotas[ws] = tracker

    STATE.approvals.requests.clear()
    for rid, row in dict(snapshot["approvals"]).items():
        STATE.approvals.requests[rid] = ApprovalRequest.model_validate(row)

    STATE.experiments.clear()
    STATE.experiments.update(dict(snapshot["experiments"]))

    STATE.metrics_counters.update(dict(snapshot.get("metrics_counters") or {}))

    # Oldest first: the export is newest-first for a reader, and replaying it in
    # that order would chain every entry to its successor.
    STATE.audit.restore(list(reversed(list(snapshot["audit"]))))

    return {
        "restored": True,
        "users": len(STATE.users),
        "experiments": len(STATE.experiments),
        "audit_entries": len(snapshot["audit"]),
        "chain_verified": STATE.audit.verify_chain(),
    }


@route("POST", "/api/v1/auditor-grants")
def _issue_auditor_grant(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    """Issue a time-boxed, watermarked, read-only grant to an outside reviewer.

    `auditor_grant` had no caller: the role, the expiry and the watermark all
    existed and there was no way to obtain one, so "auditor mode" was a
    capability nobody could use.

    The token is returned exactly once, here, and never again -- the store keeps
    only a hash. An endpoint that could re-read an issued token would make the
    hashing pointless.
    """
    if user is None:
        return 401, {"error": "unauthorized"}
    if not authorize(user, "manage_members", user.workspace_id):
        return 403, {"error": "forbidden"}
    name = str(body.get("auditor_name") or "").strip()
    if not name:
        return 400, {"error": "auditor_name is required"}
    try:
        ttl_days = int(body.get("ttl_days", 14))
    except (TypeError, ValueError):
        return 400, {"error": "ttl_days must be an integer"}
    if ttl_days < 1:
        return 400, {"error": "ttl_days must be at least 1"}

    grant = auditor_grant(
        STATE.tokens,
        STATE.users,
        auditor_name=name,
        workspace_id=user.workspace_id,
        issued_by=user.user_id,
        ttl_days=ttl_days,
    )
    STATE.audit.append(
        actor=user.user_id,
        action="auditor.grant",
        target=name,
        details={"ttl_days": ttl_days, "workspace_id": user.workspace_id},
    )
    return 201, grant


@route("GET", "/api/v1/export")
def _export(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    # A full snapshot is every workspace's data at once, so it is an admin
    # operation rather than a workspace-scoped read.
    if not authorize(user, "manage_policies", user.workspace_id):
        return 403, {"error": "forbidden"}
    STATE.audit.append(actor=user.user_id, action="state.export", target="server")
    return 200, export_state()


@route("POST", "/api/v1/import")
def _import(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    if user is None:
        return 401, {"error": "unauthorized"}
    if not authorize(user, "manage_policies", user.workspace_id):
        return 403, {"error": "forbidden"}
    try:
        result = import_state(dict(body.get("snapshot") or {}))
    except SnapshotError as exc:
        return 400, {"error": str(exc)}
    # Appended *after* the restore, so the record of the restore survives it.
    STATE.audit.append(actor=user.user_id, action="state.import", target="server")
    return 200, result


@route("POST", "/api/v1/retention")
def _retention(body: dict[str, Any], user: User | None) -> tuple[int, dict[str, Any]]:
    """Apply the retention policy to experiments. Administrative, not legal.

    `apply_retention` has been written and tested since the server was, with no
    caller outside its own tests, while the console's settings page described it
    to operators as a working feature. This is the caller.

    `dry_run` defaults to **true**. A deletion endpoint whose default is to
    delete is one somebody triggers while exploring.
    """
    if user is None:
        return 401, {"error": "unauthorized"}
    if not authorize(user, "manage_policies", user.workspace_id):
        return 403, {"error": "forbidden"}
    try:
        max_age_days = int(body.get("max_age_days", 90))
    except (TypeError, ValueError):
        return 400, {"error": "max_age_days must be an integer"}
    if max_age_days < 1:
        return 400, {"error": "max_age_days must be at least 1"}

    hold = {str(h) for h in (body.get("legal_hold_ids") or [])}
    dry_run = body.get("dry_run", True) is not False
    records = [
        {**e, "id": e.get("id"), "created_at_epoch": float(e.get("created_at_epoch", time.time()))}
        for e in STATE.experiments.values()
    ]
    keep, deleted = apply_retention(records, max_age_days, time.time(), hold)
    if not dry_run:
        for rid in deleted:
            STATE.experiments.pop(rid, None)
        STATE.audit.append(
            actor=user.user_id,
            action="retention.apply",
            target="experiments",
            details={"deleted": len(deleted), "max_age_days": max_age_days},
        )
    return 200, {
        "dry_run": dry_run,
        "max_age_days": max_age_days,
        "kept": len(keep),
        "deleted": deleted,
        "legal_hold_ids": sorted(hold),
        "statement": (
            f"{len(deleted)} experiment(s) past {max_age_days} days"
            + (f", {len(hold)} held" if hold else "")
            + (". Nothing was deleted: this was a dry run" if dry_run else ". Deleted.")
            + " Administrative retention only -- this is not a legal-compliance determination"
        ),
    }


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
            token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else None
            user = _token_user(token) if token else None
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
            self._send_json(status, payload, watermark=_token_watermark(token))

        def _send_json(
            self, status: int, payload: dict[str, Any], *, watermark: str | None = None
        ) -> None:
            # In the body as well as a header. A client that renders the body
            # and ignores headers -- which is most of them -- would otherwise
            # display an auditor's view with nothing marking it as one.
            if watermark:
                payload = {**payload, "watermark": watermark}
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            if watermark:
                self.send_header("X-ToolTrace-Watermark", watermark)
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
