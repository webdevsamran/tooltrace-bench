# Changelog

All notable changes to ToolTrace Bench are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased] — Second transformation pass (2026-08-23)

### Added
- **Protocol & data governance:** task protocol v2 (domain, difficulty, deterministic
  seeds, capability requirements, allowed side effects, scoring contracts) with v1
  migration readers; task provenance manifests; semver task-pack indexes with
  compatibility ranges; contamination-aware metadata; cross-pack fingerprint dedup;
  deterministic synthetic task-generation SDK.
- **Task packs & interfaces:** coding, OS/fileops, database, mock-API workflow,
  local web environment, knowledge-retrieval, spreadsheet/data-transform, git
  workflow, DevOps fixtures and defensive-security packs; multimodal attachment
  schema; voice-agent fixture interface; desktop/GUI and mobile abstractions;
  human-in-the-loop states; dual-control tasks; multi-agent role definitions;
  adversarial-but-safe robustness tasks; long-horizon checkpointed tasks;
  prerequisites and resource budgets.
- **Quality gates:** `tooltrace lint` (ambiguous scoring, unreachable assertions,
  undeclared side effects, missing cleanup, unsafe network), `tooltrace dry-run`,
  suite manifests, fixed/stratified/seeded sampling policies with recorded
  selection manifests.
- **Metrics:** pass@k / pass^k with confidence intervals; trajectory efficiency
  (per step/tool-call/token/wall-time); recovery vs agent-caused failure metrics;
  policy-compliance scoring; side-effect correctness; change minimality;
  verification quality; loop/stagnation detection; hallucinated-resource metrics;
  context retention; abstention calibration; outcome-vs-trajectory dual scoring;
  judge-independent deterministic scoring with judge dependency reported.
- **Adapters & integrations:** multi-judge disagreement reporting + calibration
  sets; scorer plugin API v2 with conformance tests; provider metadata
  normalization; OpenAI-/Anthropic-/Gemini-compatible and local subprocess
  adapters (optional extras); MCP client support + server conformance fixtures;
  A2A abstraction hook; capability negotiation; recorded retry/backoff;
  rate-limit telemetry; per-adapter doctor checks; env/keychain secret resolution;
  explicit price-table cost accounting.
- **Execution engine:** experiment manifests; distributed coordinator with
  deterministic run IDs; bounded-concurrency local execution; worker capability
  inventory; resumable checkpoints; cancellation/cleanup; failure-isolated
  workers; fair queues; sharding/merge utilities.
- **Analysis & reproducibility:** cohort compatibility enforcement; baselines at
  suite/domain/task/metric level; trend analysis with composition warnings;
  paired-run analysis; effect-size reporting; bootstrap/Bayesian extras;
  reliability frontier charts; failure clustering; root-cause drill-down;
  reproducibility score; full/partial replay; redaction policies; trace
  compression/streaming; binary artifact manifests; trace schema migrations;
  signed bundles; tamper-evident checksums; invalidation/supersession records;
  snapshot generation/verification (`tooltrace snapshot`); cohort-safe
  leaderboards; anti-gaming checks.
- **Infrastructure:** image-digest provenance; Podman support; Windows-native
  sandbox interface; Kubernetes job-runner backend; resource telemetry; network
  policy profiles (offline / local-fixtures-only / allowlist); deterministic clock
  injection; fault-injection framework; chaos/recovery suites; harness self-test
  (`tooltrace self-test`); authoring studio APIs; catalog metadata; contribution
  quality checks.
- **Self-hosted server** (`tooltrace server`): workspaces with strict tenant
  scoping; RBAC (viewer/runner/task_author/reviewer/admin/service_account);
  hashed rotatable API tokens; local-dev auth + OIDC/SAML hooks; policy-as-code;
  approval workflows; hash-chained immutable audit log; quotas (HTTP 429);
  HMAC-signed webhooks with retries; retention with legal-hold exemptions; REST +
  SSE + Prometheus `/metrics` + `/healthz` + `/readyz` + `/openapi.json`;
  request body size limits; backup/export tooling; air-gapped posture docs.
- **Frontend:** Trace Explorer (filterable expandable timeline, raw JSONL
  download), Recovery Analysis, Cost·Latency·Efficiency, Dataset/Snapshot browser,
  Plugin Catalog; nav/routes wired into the existing console.
- **Docs:** documentation map, getting started, CLI reference, architecture
  pipeline diagram, self-hosting guide, troubleshooting/FAQ; competitive analysis
  with verified evidence matrix (`docs/competitive-analysis.md`,
  `data/competitive-capabilities.json`), `PRODUCT_GAPS.md`, `DIFFERENTIATORS.md`.

### Changed
- CI action pins bumped to current immutable SHAs (setup-python, codeql-action,
  configure-pages) per Dependabot #18.
- README gained a Documentation section linking the full hierarchy.

### Security
- Secret scan clean across all paths; request body limits on server endpoints;
  tenant-scoped authorization tests; offline-by-default sandbox network posture.

### Removed
- Stray generated artifacts from version control (`results/_refcheck.txt`).

## [0.1.0] — Initial public beta

First release: typed core engine, CLI (run/benchmark/showdown/compare/baseline/
regression/validate/reproduce/report/export/serve/task), scripted + subprocess +
OpenAI-compatible agents, temp-workspace and Docker sandboxes, deterministic
scorers, `.tooltrace` bundles with checksums, React frontend, tests and CI.