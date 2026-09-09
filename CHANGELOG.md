# Changelog

All notable changes to ToolTrace Bench are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **A built wheel could not load a single task.** `[tool.hatch.build.targets.wheel]`
  packaged only `tooltrace`, so the JSON Schemas authored at the repository root
  never entered the distribution. `tasks/loader.py` looked for a repo-root
  `schemas/` directory and otherwise fell back to
  `resources.files("tooltrace") / "schema_data"` — a directory that did not exist
  either — on a branch annotated `# pragma: no cover`, so no test ever executed
  it. Every `pip install` of a wheel produced a package where
  `validate_task_document` raised `task.schema.json not found` for *every* task:
  no `tooltrace tasks`, no `tooltrace run`, nothing. It stayed invisible because
  the documented quickstart installs editable from a checkout, where the repo
  copy resolves and the broken branch never runs, and because PyPI publishing is
  gated off so nobody had installed one.

  The schemas are now copied into the wheel by a hatch `force-include`, and
  resolution moved to `tooltrace/core/schemas.py`, which prefers the packaged
  copy so an installed package can never silently depend on a checkout being
  nearby. The `pragma: no cover` is gone: both roots are ordinary arguments to
  `load_schemas_from`, so each is unit-tested.

  Checking a source tree could not have caught this, so `scripts/wheel_check.py`
  builds a real wheel, extracts it outside the repository, asserts the import
  actually came from the extract (otherwise the check would pass vacuously), and
  runs the call that used to raise. It runs in CI and is covered by
  `tests/test_wheel_ships_schemas.py`, including a test that stripping the
  schemas back out is detected.

### Added
- `tooltrace doctor` now reports `schema_source` and `schemas_loaded`, so a
  broken install is one line of diagnosis rather than a `TaskValidationError` on
  every task.

### Fixed
- **Every shipped trace carried duplicate `seq` values.** The runner and the tool
  executor each kept an event counter; the runner passed its current value as
  `seq_start` — by value, at construction — and both then advanced
  independently. A twelve-event trace shipped with five duplicated sequence
  numbers, and `seq` was not monotonic in file order. Since
  `replay_from_checkpoint` partitions a trace on `e.seq >= checkpoint_seq`, it
  was partitioning on an ambiguous key. Both writers now share one `SeqCounter`.
  `tests/test_trace_seq_is_unique.py` checks the committed bundle corpus, which
  is the test that would have caught this when the traces were authored.
- **A flawless partial replay reported failure.** `replay_from_checkpoint` put
  its informational "skipped the prefix" line into `ReplayReport.errors`, and
  `ok` is `not mismatched and not errors`, so `ok` was unreachable. The note was
  only ever meant to stop callers mistaking a partial replay for a full one; it
  now lives in a separate `notes` field.
- **`showdown` declared an order it could not support.** It sorted on the
  success-rate point estimate, carried a confidence interval in its own output
  and never consulted it, so two agents at `--runs 1` came back definitively
  ranked. It now reports `verdict: "not distinguishable at this sample size"`
  unless the sample clears `significance_note`'s threshold *and* the leader's
  Wilson interval is disjoint from the runner-up's, and attaches `paired_delta`
  and Cohen's *h* per challenger. `paired_delta`, `effect_size_cohens_h` and
  `significance_note` had shipped since 0.2.0 with no caller outside the tests;
  the per-agent `flakiness` block was computed and silently dropped. Output is
  now an object rather than a bare list.

- **Replay never injected the faults a task declares.** `replay_trace` built a
  `PerturbationEngine` and prepared its workspace, but never passed `engine.hook`
  to the executor, so any task carrying a perturbation replayed as a mismatch —
  including this repository's own `failure-recovery/retry-after-tool-failure`.
  Partial replay additionally now primes the engine over the skipped prefix
  (`PerturbationEngine.prime`), so a one-shot fault already spent there is not
  injected again on the first replayed call.

## [0.3.0] — Ecosystem, adoption and integrity pass (2026-09-07)

### Fixed — integrity pass
- **README sample run is now captured, not written.** The section headed "A
  real sample run", prefaced "no fabricated numbers", showed output for a task
  that does not exist, with score components no scorer emits and a `wall_ms`
  traceable to the frontend's demo fixture. Replaced with real output, and
  `tests/test_readme_is_truthful.py` re-runs the documented command and diffs
  every deterministic field against the README.
- **The quickstart could not be followed** — a nonexistent task id, a `--pack`
  flag the CLI never had, and 12 of 12 wrong task-pack names. Checking the rest
  of the docs the same way found broken invocations for `showdown`, `baseline`,
  `regression`, `task scaffold/validate/test` and `snapshot`; all corrected
  against real `--help` output, with a test that every documented flag exists.
- **Four CLI bugs** surfaced by running the documented commands: `task
  scaffold` wrote its file then crashed on an undefined `args.json`; `snapshot
  --output` did not create parent directories; `verify_bundle` let
  `BundleError` escape as a raw traceback; `cmd_regression` parsed
  `--thresholds` outside its try block.
- **The SBOM described the build machine, not the project** — 147 components
  against six declared dependencies, including two unrelated sibling projects,
  with no serialNumber or timestamp. Now resolves the declared dependency
  closure (40 components). Both workflows also called `cyclonedx-py
  requirements`, which could never run here; `release.yml` had no fallback, so
  a real tagged release would have failed at that step.
- **Version claims disagreed**: CITATION.cff and SECURITY.md described 0.1.x
  while the package was 0.2.1.


### Added
- **External trace ingestion** (`tooltrace ingest`, `tooltrace.ingest`): convert
  traces produced outside the harness into ToolTrace trace events so they can be
  classified with the failure taxonomy, replayed and scored by the standard
  pipeline. Formats: OTel GenAI semantic-convention spans (`otel-spans`) and
  plain assistant-step records (`openai-steps`). Observability platforms become
  data sources instead of competitors.
- **pytest integration** (`pytest11` entry point, auto-enabled on install):
  `tooltrace_runner`, `run_tooltrace(...)` and `assert_tooltrace_pass(...)`
  fixtures plus a `tooltrace` marker — run agent tasks as native pytest tests
  with taxonomy-aware diagnostics.
- **Assertion-builder DSL** (`tooltrace.dsl`): typed Python builders mirroring
  every built-in deterministic scorer (`file_exists`, `file_contains`,
  `json_schema`, `command_exit`, …) with authoring-time validation via pydantic;
  includes a `custom()` escape hatch for third-party scorers.
- 17 new tests covering DSL end-to-end scoring, both ingestion formats
  (event-shape, seq monotonicity, JSON-argument decoding), the CLI `ingest`
  command (happy path + usage errors) and real subprocess-level pytest-plugin
  behavior.

## [0.2.1] — Reliability platform, final pass (2026-08-26)

### Changed
- **Repository structure pass:** flat modules organized into cohesive packages —
  `tooltrace/artifacts/` (bundles, reproduction) and `tooltrace/analysis/`
  (comparisons, baselines/trends/snapshots, failure classification, statistics);
  `perturbations`, `replay` and `reports` are now packages. Deprecated shims
  keep every pre-0.2 import path working (`tooltrace.bundles`, `.stats`,
  `.compare`, `.failures`, `.bundles_repro`).
- **Frontend restructure:** numbered continuation modules removed — the team
  console now lives in semantic per-page modules under
  `web/src/pages/workspace/`; the pure pass@k estimator moved to
  `web/src/lib/passAtK.ts`.
- **Tests renamed by domain** (formerly pass-named "gaps" files): failure
  classification, perturbation/SDK, repro/security, scorers/tools, agent
  adapters, CLI commands, docker-sandbox guard.
- Version alignment across `pyproject.toml`, `FRAMEWORK_VERSION`, classifiers
  (Python 3.11–3.14) and this changelog (0.2.0/0.2.1 released); coverage
  `fail_under = 80` enforced from configuration.
- Docs consolidated under `docs/`: product gaps, differentiators and threat
  model (renamed lowercase); broken tables in `feature-status.md` repaired;
  module map synchronized with reality (including the argparse CLI correction).

### Fixed
- **Hermetic test imports:** `tests` is now a regular package, so conftest
  imports can never resolve against a foreign `tests` namespace package on
  `sys.path` (previously broke 6 test modules on machines with other
  checkouts).
- **Real hook-order bug** in Reliability Trends (conditional `useMemo`
  after early returns), caught by the newly enforced react-hooks rules.

### Added
- **CLI signature workflows:** `tooltrace perturb` (safe fault injection with
  recovery-rate measurement and a `--min-recovery-rate` CI gate) and
  `tooltrace trace` (checksum-verified terminal trace inspection with
  filtering and assertions-only view). Both were promised by the README but
  had no implementation; they now exist with tests and smoke coverage (190
  Python tests total).
- **Team console frontend:** 14 self-hosted routes — workspace dashboard,
  experiments + builder + live SSE monitor, workers/capacity, baselines &
  regressions, Task Authoring Studio (client-side lint pre-checks mirroring
  `tooltrace lint`, assertion workflow graph), publication review queue,
  users & service accounts, policies & budgets, audit log, webhooks,
  retention/settings and system health. Backed by the same dual-mode data
  layer: static validated JSON on Pages or the self-hosted REST/SSE server;
  DEMO-labeled fixtures for offline preview only.
- **Charts:** dependency-free accessible SVG charts — multi-series line,
  histogram, scatter, domain×agent heatmap, utilization rings; wired into
  leaderboard, trends, efficiency pages and workers.
- **Frontend resilience:** route-level code splitting, error boundary,
  offline banner, virtualized Trace Explorer for large traces.
- **E2E & accessibility:** 23 Playwright tests (route smoke with zero-console-
  error assertions, axe wcag2a/2aa serious-violation gate, keyboard nav) plus
  18 vitest unit/component tests; ESLint actually installed and enforced.
- **Docs:** migration guide (protocol v1→v2), enterprise deployment,
  plugins & extensions, schemas & protocols, recipes; docs map updated.

### Changed
- CI: dependency audit is now a blocking gate (`pip-audit --skip-editable`,
  no more `|| echo` escapes); Windows/macOS test matrix added; frontend job
  runs lint + unit + e2e/a11y against the production build.
- Release: new tag-triggered pipeline (validate → test → build sdist/wheel →
  build frontend → CycloneDX SBOM → SHA256SUMS → SLSA provenance attestation
  → GitHub Release); PyPI publishing only via an explicit Trusted Publishing
  environment flag. All action pins verified against the GitHub API.
- WCAG AA color tokens: light muted/accent/warn darkened to pass contrast
  (failures found by the new axe scans).

## [0.2.0] — Second transformation pass (2026-08-23)

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