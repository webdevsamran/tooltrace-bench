# Self-Hosting & Teams

ToolTrace ships a dependency-free server (`tooltrace server`) suitable for a
single laptop up to a team deployment. It is a modular monolith: pure-logic
services plus a stdlib HTTP layer.

## Run

```bash
tooltrace server --host 127.0.0.1 --port 8737
curl http://127.0.0.1:8737/healthz     # liveness
curl http://127.0.0.1:8737/readyz      # readiness (users configured + audit chain intact)
curl http://127.0.0.1:8737/openapi.json
```

## Capabilities

- **Workspaces** with strict tenant scoping — users only see their own workspace's data.
- **RBAC roles**: viewer, runner, task_author, reviewer, admin, service_account.
- **API tokens**: hashed at rest (SHA-256), scoped permissions, rotation metadata.
- **Auth providers**: local-dev provider out of the box; OIDC/SAML hook accepts an
  external verifier callback (bring your own IdP integration).
- **Policy-as-code** per workspace: allowed providers/models/tools/packs, network
  modes, publication approval requirement.
- **Approvals**: privileged actions (e.g., publishing results) require admin decision.
- **Audit log**: immutable hash-chained events (`AuditLog.verify_chain()`).
- **Quotas**: per-workspace limits (runs, concurrency, tokens, budget) → HTTP 429.
- **Webhooks**: HMAC-SHA256 signed deliveries with retry policy.
- **Retention**: age-based deletion with legal-hold-style exemptions.
- **Observability**: Prometheus text metrics at `/metrics`, SSE event stream at
  `/api/v1/events`, request body size limits.

## Endpoints (v1)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/healthz`, `/readyz`, `/metrics`, `/openapi.json` | none/metrics | ops |
| POST | `/api/v1/experiments` | Bearer token | RBAC + quota enforced; audited |
| GET | `/api/v1/experiments` | Bearer token | tenant-scoped listing |
| POST | `/api/v1/approvals` | Bearer token | request privileged action |
| POST | `/api/v1/approvals/{id}/decide` | Bearer token | admin-only decision |
| GET | `/api/v1/events` | — | SSE snapshot stream |

## Air-gapped operation

Default network posture is offline. Container sandboxes default to no network;
policy can restrict to `local-fixtures-only` or explicit allowlists. No telemetry
is sent anywhere; all data stays under your configured directories.

## Honest boundaries

Multi-user PostgreSQL scaling, Kubernetes worker farms and SSO are *interfaces*
today (hooks, job-runner abstraction) — validate them in your environment before
production use. No compliance certification is claimed by the presence of controls.