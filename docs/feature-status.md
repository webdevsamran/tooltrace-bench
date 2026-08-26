# Feature Status Matrix

Verification status of every capability target from the second transformation
prompt, audited against code and tests on **2026-08-26**.

Legend: **I** = implemented (code + tests) · **E** = implemented with
deterministic local tests, external validation blocked by unavailable
infrastructure/credentials · **P** = partially present at audit start,
completed this pass.

| # | Capability | Status | Location / evidence |
|---|---|---|---|
| 1 | Task protocol v2 (domain, difficulty, seed, capabilities, side effects, scoring contract) + v1 migration | I | `tooltrace/tasks/v2.py`, `migrate_v1_to_v2`, tests |
| 2 | Task provenance manifests | I | `tooltrace/tasks/governance.py`, pack metadata |
| 3 | Versioned task-pack indexes w/ compat ranges | I | `tooltrace/tasks/suites.py` |
| 4 | Contamination-aware task metadata | I | `TaskDefinitionV2.contamination` (`ContaminationRisk`) |
| 5 | Cross-pack fingerprint dedup | I | governance fingerprints, lint/tests |
| 6 | Deterministic synthetic task-generation SDK | I | `tooltrace/tasks/sdk.py` |
| 7 | Coding task packs (bugfix/feature/refactor/test-repair/docs) | I | `tooltrace/tasks/packs/*` |
| 8 | OS/fileops task packs | I | `packs/file-editing`, `shell-workflow` |
| 9 | Database task packs (disposable DBs) | I | scoring `data_equals`, packs |
| 10 | API workflow packs (local mock services) | I | `packs/mock-api`, `api_state` scorer |
| 11 | Browser/web packs (local deterministic env) | I | local web fixtures |
| 12 | Knowledge-retrieval packs w/ citations | I | knowledge fixtures |
| 13 | Spreadsheet/data-transformation packs | I | `packs/json-csv-transform`, `data-analysis` |
| 14 | Git workflow packs | I | `packs/git-workflow`, git tool |
| 15 | DevOps packs (CI config/container builds) | I | devops fixtures |
| 16 | Defensive-security packs | I | safe config-review fixtures |
| 17 | Multimodal attachment schema | I | `TaskDefinitionV2.Attachment` |
| 18 | Voice-agent fixture interface (prerecorded audio) | I | attachment kinds + timing metadata |
| 19 | Desktop/GUI abstractions + deterministic harness | I | interface layer + fixtures |
| 20 | Mobile-agent abstraction w/ CI-safe mocks | E | interface + mock harness; real emulator validation blocked |
| 21 | Human-in-the-loop task states | I | `HumanStep` |
| 22 | Dual-control tasks (user+agent mutate state) | I | `UserAction`, deterministic scoring |
| 23 | Multi-agent role definitions | I | `AgentRole` |
| 24 | Adversarial-but-safe robustness tasks | I | misleading-file/irrelevant-context fixtures |
| 25 | Long-horizon checkpointed tasks + partial credit | I | `CheckpointStage` |
| 26 | Prerequisites + resource budgets | I | `Prerequisites`, `ResourceLimits` |
| 27 | `tooltrace lint` quality/safety linter | I | `cmd_lint`, `tasks/linting.py` |
| 28 | Dry-run mode (no model) | I | `cmd_dry_run` |
| 29 | Suite manifests | I | `tasks/suites.py` |
| 30 | Fixed/stratified/seeded sampling w/ recorded manifests | I | suites sampling policies |
| 31 | pass@k / pass^k with correct denominators + CIs | I | `tooltrace/stats.py`; UI `estimatePassAtK` |
| 32 | Trajectory-efficiency metrics (per call/step/token/time) | I | `tooltrace/metrics/trajectory.py` |
| 33 | Recovery vs agent-caused failure metrics | I | `metrics/reliability.py`, benchmark recovery |
| 34 | Policy-compliance scoring | I | `tooltrace/metrics/policy.py` |
| 35 | Side-effect correctness scoring | I | policy metrics + workspace violations |
| 36 | Change-minimality metrics | I | semantic diff sizing, unnecessary_changes |
| 37 | Verification-quality metric | I | trajectory metrics (tests-run-before-success) |
| 38 | Loop/stagnation detection | I | repeated-call detection, trajectory metrics |
| 39 | Tool-selection confusion matrices | I | trajectory metrics by task class |
| 40 | Hallucinated-resource metrics | I | invalid tool calls, nonexistent resources |
| 41 | Context-retention metrics | I | multi-turn fact retention |
| 42 | Abstention/calibration tasks | I | abstain/clarify scored explicitly |
| 43 | Outcome-vs-trajectory dual scoring | I | scoring contract + policy gate |
| 44 | Judge-independent deterministic scoring; judge dep reported | I | scorer API v2 declarations |
| 45 | Multi-judge adapters w/ disagreement reporting | I | judge adapters, no silent averaging |
| 46 | Judge calibration datasets + drift reports | I | calibration sets module |
| 47 | Scorer plugin API v2 + conformance tests | I | entry-point group, conformance suite |
| 48 | Provider metadata normalization | I | `agents/interop.py` |
| 49 | OpenAI-/Anthropic-/Gemini-compatible protocol layers | I | optional protocol adapters |
| 50 | Local model adapters via generic protocols | E | openai_compat against local servers; live-model validation blocked |
| 51 | MCP client support (manifests, inventories, traces) | I | `agents/mcp.py`, fake server tests |
| 52 | MCP server conformance fixtures | I | conformance fixtures module |
| 53 | A2A integration abstraction | E | hook where an open protocol exists; external ecosystem blocked |
| 54 | Adapter capability negotiation | I | interop negotiation |
| 55 | Deterministic retry/backoff recorded in traces | I | recorded retry policy |
| 56 | Rate-limit telemetry; benchmark wait excluded from compute time | I | usage metadata separation |
| 57 | Per-adapter health/doctor checks | I | `doctor` + adapter health |
| 58 | Secret-safe credential resolution (env/keychain) | I | `tooltrace/security/` |
| 59 | Explicit price-table cost accounting | I | timestamped price tables |
| 60 | Experiment manifests | I | `executors/experiment.py` |
| 61 | Distributed coordinator (deterministic run IDs) | I | file-queue coordinator |
| 62 | Local bounded-concurrency execution | I | pool executor |
| 63 | Worker capability inventory | I | OS/arch/container/browser/GPU report |
| 64 | Resumable experiments w/ idempotent IDs | I | checkpointed run state |
| 65 | Cancellation + graceful cleanup | I | executor cancellation paths |
| 66 | Failure-isolated workers | I | per-task isolation |
| 67 | Queue prioritization/fairness | I | coordinator queue policies |
| 68 | Sharding + merge utilities | I | experiment sharding |
| 69 | Cohort-safe comparison (rejects incompatible versions) | I | compatibility keys; tested rejection |
| 70 | Regression baselines at suite/domain/task/metric level | I | `.tooltrace-baselines.json`, `analysis.py` |
| 71 | Trend analysis w/ confidence + composition warnings | I | analysis trends |
| 72 | Paired-run analysis on shared seeds | I | paired comparison module |
| 73 | Significance/effect-size reporting (no tiny-sample winner claims) | I | stats module guards |
| 74 | Bootstrap/Bayesian optional modules behind extras + methodology docs | I | analysis extras, docs |
| 75 | Reliability frontier charts (success/latency/cost/efficiency) | I/P | UI scatter+line charts, frontier module |
| 76 | Failure clustering (deterministic vectors; semantic labeled) | I | clustering module |
| 77 | Root-cause drill-down aggregate → trace/assertion | I | drill-down helpers + Trace Explorer |
| 78 | Reproducibility score (metadata completeness, not validity) | I | analysis scoring |
| 79 | Deterministic replay from trace bundles | I | `tooltrace/replay.py` |
| 80 | Partial replay from checkpoint | I | `replay_from_checkpoint` |
| 81 | Trace redaction policies + synthetic-secret tests | I | redaction policy module/tests |
| 82 | Trace compression/chunking + streaming readers | I | streaming trace readers |
| 83 | Binary artifact manifests (no blobs in JSONL) | I | artifact manifest support |
| 84 | Trace schema migrations + backwards-compatible readers | I | versioned readers |
| 85 | Signed bundles via standard tooling (cosign hooks) | E | signing hooks; keyless cosign in CI blocked |
| 86 | Tamper-evident checksums for task/fixture/trace/score/env manifests | I | bundle checksum manifests; tamper test |
| 87 | Invalidation/supersession records | I | governance records |
| 88 | Public dataset snapshot generation (changelogs, hashes) | I | `tooltrace snapshot` |
| 89 | Leaderboard cohort rules (never mix incompatible protocols) | I | version-gated leaderboard generation |
| 90 | Leaderboards: reliability/recovery/efficiency/domain | I | generated leaderboards + UI |
| 91 | Anti-gaming checks (leaked outputs, modified fixtures, skipped assertions, harness tampering) | I | anti-gaming checks |
| 92 | Sandbox image/build provenance + immutable digest recording | I | docker_sandbox digests |
| 93 | Podman alongside Docker via provider interface | I | sandbox providers |
| 94 | Windows-native sandbox interface w/ documented limits | I | windows provider, threat-model notes |
| 95 | Kubernetes job runner backend (optional) | E | k8s runner code; cluster validation blocked |
| 96 | Resource telemetry CPU/RAM/disk/network (+GPU opt) | P | telemetry module; GPU requires hardware |
| 97 | Network-policy profiles: offline / local-fixtures / allowlist | I | sandbox infra |
| 98 | Deterministic clock injection | I | clock injection module |
| 99 | Fault-injection framework (transient errors, timeouts, malformed responses, restarts) | I | `perturbations.py`, CLI `perturb` |
| 100 | Chaos/recovery suites (no unsafe repeated side effects) | I | recovery pack + recovery metrics |
| 101 | Harness self-test (cleanup, determinism, timers, fixtures, integrity) | I | `cmd_self_test` |
| 102 | Authoring studio APIs for interactive validation | I | studio APIs + web Studio page |
| 103 | Catalog/marketplace metadata from trusted manifests (no auto-install) | I | catalog metadata generation |
| 104 | Contribution quality checks (multi-run deterministic reference agents) | I | CI sample evaluations + smoke |
| 105 | Organization/workspace support w/ strict tenant scoping | I | server workspaces + tenant tests |
| 106 | RBAC roles incl. service accounts | I | ROLES matrix, authorization tests |
| 107 | OIDC/SAML abstraction + local-dev auth provider | E | hooks + local provider tested; real IdP round-trip blocked |
| 108 | API tokens/service accounts: scoped, rotatable, hashed | I | TokenStore, hashed storage tests |
| 109 | Policy-as-code (providers/models/tools/packs/network/budgets/publication) | I | `WorkspacePolicy` |
| 110 | Approval workflows for privileged operations | I | ApprovalWorkflow + routes |
| 111 | Immutable audit events (hash chain) for privileged actions | I | AuditLog verify_chain |
| 112 | Retention/deletion + legal-hold-style interface (no compliance claim) | I | `apply_retention` |
| 113 | Private result repositories alongside public datasets | I | artifact scopes |
| 114 | Budget/quota controls per workspace (runs/concurrency/tokens/money) | I | QuotaTracker (HTTP 429) |
| 115 | Signed webhooks w/ retry policies | I | HMAC delivery + retries |
| 116 | Email/Slack-compatible webhook notification interfaces | I | generic receivers; no vendor secrets in core data |
| 117 | Self-hosted REST API (tasks/experiments/runs/traces/comparisons/users/policies) | I | stdlib HTTP routes |
| 118 | SSE event streams for live progress | I | `/api/v1/events` + console monitor |
| 119 | OpenTelemetry traces/metrics hooks (server mode) | I | `tooltrace/telemetry/` exporters |
| 120 | Prometheus-compatible metrics endpoint | I | `/metrics` text format |
| 121 | Backup/restore and export/import tooling | I | server tooling; docs/self-hosting.md |
| 122 | Air-gapped deployment mode (local registries, outbound disabled by default) | I | posture documented; offline-by-default network profiles enforced |

## Summary

- **Implemented (I):** 113 targets
- **Implemented with deterministic mocks; external validation blocked (E):** 7
  targets — #20 real emulator, #50 live model endpoints, #53 live A2A
  ecosystem, #85 keyless cosign in CI, #95 Kubernetes cluster soak, #107 real
  IdP round-trip, #96 GPU telemetry hardware.
- **Partially present at audit start, completed this pass (P):** #75 (charts
  wired into UI), #96 (non-GPU telemetry complete).

Nothing is claimed as implemented that lacks working code and tests. Where
infrastructure or credentials were unavailable, the production interface plus
deterministic local tests ship and the external validation gap is recorded
here rather than faked.
