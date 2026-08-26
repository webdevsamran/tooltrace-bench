# Enterprise Deployment

ToolTrace Bench is local-first: a single laptop runs the full CLI, engine and
frontend without any server. This document describes the **optional**
self-hosted deployment path for teams and enterprises. Nothing here is
required for individual use, and no community functionality is crippled to
sell scale.

> Honest boundary: controls described here are engineering mechanisms.
> ToolTrace Bench makes **no** SOC 2 / ISO 27001 / HIPAA / GDPR compliance
> claims. Certification, if desired, is an organizational process outside
> this repository.

## Deployment tiers

| Tier | What it adds | How |
|---|---|---|
| Community (local) | everything in the CLI/SDK/engine + static frontend | `pip install -e ".[dev]"`, `tooltrace run …` |
| Team / self-hosted | shared experiments, RBAC, policies, audit, webhooks | `tooltrace server` on one host |
| Enterprise-ready | SSO hooks, air-gapped registries, k8s worker farms, retention & backup discipline | this page |

## Authentication

- Local development provider ships built-in (deterministic users/tokens).
- OIDC/SAML are **abstraction hooks** (`tooltrace/server/core.py`): plug your
  identity provider by implementing the auth-provider interface. We do not
  bundle vendor SDKs; verify your IdP integration against your own tenant.

## Topology

```
[Browser console] ──HTTPS──▶ [tooltrace server (modular monolith)]
        │                        │            │            │
   static data OR           SQLite file   artifact     audit log
   /api/v1 REST+SSE         (PostgreSQL   store        (hash chain)
                             optional)    (private /
                                          public scope)
                                   ▲
                     [workers enroll: tooltrace worker]
                      (local processes, containers, k8s jobs)
```

- **SQLite** is the default store — zero-ops for small teams. PostgreSQL is
  optional for multi-user scale; point the server at any supported DB URL.
- The coordinator schedules independent runs to registered workers while
  preserving deterministic run IDs; workers report capability inventories
  (OS/arch/container runtime/browser/GPU).

## Policy-as-code

Workspace policies govern allowed providers, models, tools, task packs,
network modes and publication. Policies are declarative records reviewed via
the publication queue; privileged actions (publish results, enable networked
tasks, change shared baselines, costly runs) require reviewer/admin approval.

## Air-gapped mode

1. Mirror PyPI packages and task packs to an internal registry.
2. Install from the mirror only: `pip install --index-url https://internal/simple tooltrace-bench`.
3. Run the server with outbound network disabled by default; sandbox network
   profiles default to `offline` / `local-fixtures-only`.
4. Frontend works fully from generated static JSON — no external CDN calls.

## Kubernetes job runner

For large evaluation farms, the k8s job runner backend executes sandboxed
runs as jobs (image digest recorded for provenance). It is optional: local
and container providers work without any cluster.

## Backup / restore · retention

- Metadata and artifact references export/import via the server tooling;
  practice restores, don't just take backups.
- Retention rules delete expired records unless under a legal-hold-style
  exemption. This is administrative deletion — not a legal-compliance claim.

## Security posture

See [THREAT_MODEL.md](THREAT_MODEL.md). Highlights: hashed rotatable API
tokens, hash-chained immutable audit log, HMAC-signed webhooks with retry,
request body size limits, quota enforcement (HTTP 429), strict tenant scoping
verified by multi-tenant authorization tests.
