# ToolTrace Bench — Documentation Map

| Document | Purpose |
|---|---|
| [Getting started](getting-started.md) | Install, first run, first benchmark |
| [CLI reference](cli-reference.md) | Every command, flags, exit codes |
| [Architecture & pipeline](architecture-pipeline.md) | Task/Pack → Experiment → … → Dataset/UI |
| [Self-hosting & teams](self-hosting.md) | Server mode: RBAC, policy, audit, quotas, webhooks |
| [Enterprise deployment](enterprise-deployment.md) | SSO hooks, air-gapped mode, k8s runners, backup/restore |
| [Plugins & extensions](plugins.md) | Entry-point groups, versioning, conformance testing |
| [Schemas & protocols](schemas-and-protocols.md) | Artifact versions, migration v1→v2, compatibility keys |
| [Migration: protocol v1 → v2](migration-v1-to-v2.md) | Field mapping and reader compatibility |
| [Feature status matrix](feature-status.md) | Verified implementation status of all 122 capability targets |
| [Recipes](recipes.md) | Copy-paste workflows for common evaluation goals |
| [Security & privacy](THREAT_MODEL.md) | Threat model and defenses |
| [Competitive analysis](competitive-analysis.md) | Verified competitor capability matrix |
| [Troubleshooting & FAQ / glossary](troubleshooting-faq.md) | Common problems, answers, glossary |

Root documents: `README.md` (landing), `ARCHITECTURE.md`, `ROADMAP.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `PRODUCT_GAPS.md`, `DIFFERENTIATORS.md`.

Schemas live in `schemas/`; generated dataset indexes in `web/public/data/`.
