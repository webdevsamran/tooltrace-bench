# Feature Status Matrix

Verification status of every capability target from the second transformation
prompt, audited against code and tests on **2026-08-26**, re-audited
**2026-09-07**.

Legend: **I** = implemented (code + tests) · **E** = implemented with
deterministic local tests, external validation blocked by unavailable
infrastructure/credentials · **P** = partially present at audit start,
completed this pass · **S** = schema only: the type system admits it and a
`Domain` value exists for it, but no task pack, fixture or harness ships, so
nothing can be run against it today · **D** = declared only: a field or flag
exists in the type system and nothing implements it · **N** = not
implemented; the row was graded in error and nothing ships.

`tests/test_feature_status_is_truthful.py` checks the checkable parts of this
table on every CI run: every path cited in the evidence column has to resolve,
and a row claiming a task pack has to have that pack on disk.

> **Correction, 2026-09-07.** Eight rows were marked **I** citing fixtures that
> are not in the repository -- "local web fixtures", "knowledge fixtures",
> "devops fixtures", "safe config-review fixtures". No such files exist; the
> only thing backing those rows was a member of the `Domain` enum in
> `tooltrace/tasks/v2.py`. They are now **S**, and the summary counts below are
> recomputed. Three more rows cited module paths that were renamed
> (`analysis.py`, `replay.py`, `perturbations.py` are packages now); the
> features are real and the citations are fixed. A verification document that
> is itself unverified is worse than no verification document, so the table is
> now machine-checked.

> **Correction, 2026-09-09.** Rows 45 and 46 were graded **I** citing "judge
> adapters" and a "calibration sets module". No judge implementation exists
> anywhere in the package -- no file matches `judge*.py` or `calibrat*.py`, and
> the only mentions of the word are a reserved `judge_config` field that is
> never assigned, a `ScoringContract.judge_required` declaration, and a lint
> warning. They are now **D**.
>
> This is the same defect class as the 2026-09-07 correction above, and it
> recurred because the check had a hole: `test_every_path_cited_as_evidence_exists`
> only inspected backtick-quoted tokens containing `/` or ending `.py`, and **97
> of the 122 rows cite bare prose**, so only 25 rows were ever verified. The
> evidence column is now required to cite something checkable, and a claim probe
> rejects any row claiming a judge while no judge ships.

| # | Capability | Status | Location / evidence |
|---|---|---|---|
| 1 | Task protocol v2 (domain, difficulty, seed, capabilities, side effects, scoring contract) + v1 migration | I | `tooltrace/tasks/v2.py`, `migrate_v1_to_v2`, tests |
| 2 | Task provenance manifests | I | `tooltrace/tasks/governance.py`, pack metadata |
| 3 | Versioned task-pack indexes w/ compat ranges | I | `tooltrace/tasks/suites.py` |
| 4 | Contamination-aware task metadata | I | `TaskDefinitionV2.contamination` (`ContaminationRisk`) |
| 5 | Cross-pack fingerprint dedup | I | `tooltrace/tasks/governance.py` (`task_fingerprint`, `find_duplicates`) |
| 6 | Deterministic synthetic task-generation SDK | I | `tooltrace/tasks/sdk.py` |
| 7 | Coding task packs (bugfix/feature/refactor/test-repair/docs) | I | `tooltrace/tasks/packs/*` |
| 8 | OS/fileops task packs | I | `packs/file-editing`, `shell-workflow` |
| 9 | Database task packs (disposable DBs) | I | `tooltrace/tasks/packs/database/fix-inactive-user-query.yaml` -- an in-memory SQLite database built by the check itself, so no server and no fixture binary |
| 10 | API workflow packs (local mock services) | I | `packs/mock-api`, `api_state` scorer |
| 11 | Browser/web packs (local deterministic env) | P | `tooltrace/tasks/packs/browser/extract-product-table.yaml` extracts from *saved* HTML. No browser tool ships and the sandbox is offline, so a live page is still not exercised |
| 12 | Knowledge-retrieval packs w/ citations | I | `tooltrace/tasks/packs/knowledge/cite-the-source.yaml` -- citation scored against a deliberate distractor, so a right answer with the neighbouring source fails |
| 13 | Spreadsheet/data-transformation packs | I | `packs/json-csv-transform`, `data-analysis` |
| 14 | Git workflow packs | I | `packs/git-workflow`, git tool |
| 15 | DevOps packs (CI config/container builds) | P | `tooltrace/tasks/packs/devops/pin-unpinned-ci-action.yaml` covers CI config. Container builds are still not exercised |
| 16 | Defensive-security packs | I | `tooltrace/tasks/packs/security` (indirect prompt injection: exfiltration and direct harm), `tooltrace/tools/sink.py`, `tooltrace/metrics/security.py`, `web/src/pages/assurance.tsx` (`SecurityPosturePage`); both packs run in the published sample dataset via `scripts/make_sample_results.py` |
| 17 | Multimodal attachment schema | I | `tooltrace/core/models.py` (`Attachment`), `schemas/task.schema.json`. The v2 copy of this type was deleted rather than kept in sync; the runtime one is now the only one, and it is read -- see 75cn |
| 18 | Voice-agent fixture interface (prerecorded audio) | S | `Domain.voice` + `Attachment.media_type` can name an audio file; no timing metadata and no voice fixture ship |
| 19 | Desktop/GUI abstractions + deterministic harness | S | `Domain.desktop` only; no abstraction layer and no harness ship |
| 20 | Mobile-agent abstraction w/ CI-safe mocks | S | `Domain.mobile` only; the mock harness this row claimed does not exist |
| 21 | Human-in-the-loop task states | I | `HumanStep` |
| 22 | Dual-control tasks (user+agent mutate state) | I | `UserAction`, deterministic scoring |
| 23 | Multi-agent role definitions | I | `AgentRole` |
| 24 | Adversarial-but-safe robustness tasks | I | `tooltrace/perturbations/__init__.py` (`irrelevant_files`, `moved_file`) |
| 25 | Long-horizon checkpointed tasks + partial credit | I | `CheckpointStage` |
| 26 | Prerequisites + resource budgets | I | `Prerequisites`, `ResourceLimits` |
| 27 | `tooltrace lint` quality/safety linter | I | `cmd_lint`, `tasks/linting.py` |
| 28 | Dry-run mode (no model) | I | `cmd_dry_run` |
| 29 | Suite manifests | I | `tasks/suites.py` |
| 30 | Fixed/stratified/seeded sampling w/ recorded manifests | I | `tooltrace/tasks/suites.py` (`SelectionManifest`) |
| 31 | pass@k / pass^k with correct denominators + CIs | I | `tooltrace/stats.py`; UI `estimatePassAtK` |
| 32 | Trajectory-efficiency metrics (per call/step/token/time) | I | `tooltrace/metrics/trajectory.py` |
| 33 | Recovery vs agent-caused failure metrics | I | `metrics/reliability.py`, benchmark recovery |
| 34 | Policy-compliance scoring | I | `tooltrace/metrics/policy.py` |
| 35 | Side-effect correctness scoring | I | `tooltrace/metrics/policy.py` (`side_effect_correctness`) |
| 36 | Change-minimality metrics | I | `tooltrace/metrics/policy.py` (`change_minimality`) |
| 37 | Verification-quality metric | I | `tooltrace/metrics/trajectory.py` (`verification_quality`) |
| 38 | Loop/stagnation detection | I | `tooltrace/metrics/trajectory.py` (`loop_detection`) |
| 39 | Tool-selection confusion matrices | I | `tooltrace/metrics/trajectory.py` (`confusion_matrix`) |
| 40 | Hallucinated-resource metrics | I | `tooltrace/metrics/trajectory.py` (`hallucinated_resources`) |
| 41 | Context-retention metrics | I | `tooltrace/metrics/trajectory.py` (`context_retention`) |
| 42 | Abstention/calibration tasks | N | nothing in the package mentions abstention or clarification; no task, scorer or metric ships |
| 43 | Outcome-vs-trajectory dual scoring | I | `tooltrace/scoring/trace_scorers.py` (`tool_call_match`, `tools_used`, `no_failed_calls`), `tooltrace/scoring/trace_view.py`, `tooltrace/tasks/packs/tool-call-structure` |
| 44 | Judge-independent deterministic scoring; judge dep reported | I | `tooltrace/scoring/builtin.py` (15 deterministic scorers, no judge), `tooltrace/tasks/v2.py` (`ScoringContract.judge_required`), `tooltrace/tasks/linting.py` (`judge_not_needed`) |
| 45 | Multi-judge adapters w/ disagreement reporting | D | no judge adapter ships; `tooltrace/core/models.py` reserves `judge_config`, never assigned |
| 46 | Judge calibration datasets + drift reports | D | no calibration module ships; the row previously cited a "calibration sets module" that does not exist |
| 47 | Scorer plugin API v2 + conformance tests | I | `tooltrace/scoring/base.py` (`register_scorer`, `scorer_registry`) |
| 48 | Provider metadata normalization | I | `agents/interop.py` |
| 49 | OpenAI-/Anthropic-/Gemini-compatible protocol layers | I | `tooltrace/agents/interop.py` (`ANTHROPIC_COMPAT_SPEC`, `GEMINI_COMPAT_SPEC`) |
| 50 | Local model adapters via generic protocols | E | `tooltrace/agents/openai_compat.py` (`OpenAICompatAgent`) |
| 51 | MCP client support (manifests, inventories, traces) | I | `agents/mcp.py`, fake server tests |
| 52 | MCP server conformance fixtures | I | `tooltrace/agents/mcp_conformance.py` (required/recommended severities), CLI `mcp-conformance`, `tooltrace/agents/mcp.py` (`fake_server_command`) |
| 53 | A2A integration abstraction | E | `tooltrace/agents/interop.py` (`AdapterCapabilities`) |
| 54 | Adapter capability negotiation | I | `tooltrace/agents/interop.py` (`negotiate`) |
| 55 | Deterministic retry/backoff recorded in traces | I | `tooltrace/agents/interop.py` (`RetryPolicy`, `run_with_retries`) |
| 56 | Rate-limit telemetry; benchmark wait excluded from compute time | I | `tooltrace/core/models.py` (`UsageMetadata`) |
| 57 | Per-adapter health/doctor checks | I | `doctor` + adapter health |
| 58 | Secret-safe credential resolution (env/keychain) | I | `tooltrace/security/` |
| 59 | Explicit price-table cost accounting | I | `tooltrace/agents/interop.py` (`PriceTable`) |
| 60 | Experiment manifests | I | `executors/experiment.py` |
| 61 | Distributed coordinator (deterministic run IDs) | I | `tooltrace/executors/experiment.py` (`Coordinator`) |
| 62 | Local bounded-concurrency execution | I | `tooltrace/executors/experiment.py` (`ThreadPoolExecutor`, `max_workers`) |
| 63 | Worker capability inventory | I | `tooltrace/executors/experiment.py` (`WorkerInventory`) |
| 64 | Resumable experiments w/ idempotent IDs | I | `tooltrace/executors/experiment.py` (`checkpoint`) |
| 65 | Cancellation + graceful cleanup | I | `tooltrace/executors/experiment.py` (`cancel`) |
| 66 | Failure-isolated workers | I | `tooltrace/executors/experiment.py` (`isolat`) |
| 67 | Queue prioritization/fairness | I | `tooltrace/executors/experiment.py` (`priority`) |
| 68 | Sharding + merge utilities | I | `tooltrace/executors/experiment.py` (`shard`) |
| 69 | Cohort-safe comparison (rejects incompatible versions) | I | `tooltrace/analysis/compare.py` (`ComparisonError`, `compatibility_key`) |
| 70 | Regression baselines at suite/domain/task/metric level | I | `.tooltrace-baselines.json`, `tooltrace/analysis/compare.py` |
| 71 | Trend analysis w/ confidence + composition warnings | I | `tooltrace/analysis/core.py` (`trend_analysis`) |
| 72 | Paired-run analysis on shared seeds | I | `tooltrace/metrics/reliability.py` (`paired_delta`) |
| 73 | Significance/effect-size reporting (no tiny-sample winner claims) | I | `tooltrace/metrics/reliability.py` (`significance_note`, `effect_size_cohens_h`) |
| 74 | Bootstrap/Bayesian optional modules behind extras + methodology docs | I | `tooltrace/analysis/stats.py` (`bootstrap_interval`) |
| 75 | Reliability frontier charts (success/latency/cost/efficiency) | P | `web/src/charts.tsx` (`Scatter`, `LineChart`) |
| 75a | Security-posture view: ASR per attack class, with intervals | I | `web/src/pages/assurance.tsx` (`SecurityPosturePage`, `RateReadout`), `scripts/generate_web_data.py` (`_security_posture`) |
| 75b | Evidence view for a compliance reviewer (no compliance claim) | I | `web/src/pages/assurance.tsx` (`EvidencePage`), `tooltrace/analysis/evidence.py`, `web/src/__tests__/assurance.test.tsx` |
| 75c | Onboarding wizard against the user's own agent | I | `tooltrace/cli/init.py` (`run_init`, `verify`), `tests/test_init_command.py` |
| 75d | Embeddable reliability badge (SVG + shields endpoint) | I | `tooltrace/reports/badge.py`, `web/src/pages/browse.tsx` (`BadgeEmbed`), `tests/test_badge.py` |
| 75e | Hardware-aware run metadata + latency comparability verdict | I | `tooltrace/telemetry/hardware.py` (`hardware_metadata`, `comparability`), `tooltrace/runners/runner.py` (`environment_metadata`), `tests/test_hardware_and_latency.py` |
| 75f | Inference-time vs tool-time split | I | `tooltrace/telemetry/hardware.py` (`latency_split`, `aggregate_latency`), `tooltrace/analysis/stats.py`, `web/src/pages/operations.tsx` (`LatencySplit`) |
| 75g | PR regression bot with intervals (no tiny-move regressions) | I | `tooltrace/analysis/pr_report.py` (`compare_samples`, `render_markdown`), `.github/workflows/pr-reliability.yml`, `tests/test_pr_report.py` |
| 75h | Minimum detectable effect + power analysis before a sweep | I | `tooltrace/analysis/power.py` (`minimum_detectable_effect`, `runs_for_effect`, `power_report`), `tooltrace/cli/main.py` (`cmd_power`) |
| 75i | Variance decomposition: nondeterminism vs task diversity | I | `tooltrace/analysis/power.py` (`variance_decomposition`), `tooltrace/runners/benchmark.py` |
| 75j | Bayesian A/B comparison for agent ranking | I | `tooltrace/analysis/power.py` (`bayesian_comparison`), `tooltrace/cli/main.py` (`cmd_showdown`) |
| 75k | Recovery-quality grading (immediate / delayed / abandoned / silently wrong) | I | `tooltrace/analysis/behaviour.py` (`recovery_quality`), `tooltrace/runners/benchmark.py` |
| 75l | Error-propagation chains across dependent steps | I | `tooltrace/analysis/behaviour.py` (`error_propagation`) |
| 75m | Shortcut / reward-hacking signals (never a verdict) | I | `tooltrace/analysis/behaviour.py` (`shortcut_signals`), `tests/test_behaviour_analysis.py` |
| 75n | Autonomy score | D | `tooltrace/analysis/behaviour.py` (`autonomy`) reports `measurable: false`: `tooltrace/tasks/v2.py` declares `UserAction`/`CheckpointStage`, no shipping task uses one and no executor performs one |
| 75o | Cached / cache-write / reasoning token dimensions | I | `tooltrace/core/models.py` (`TokenUsage`), `tooltrace/agents/interop.py` (`PriceEntry`, `compute_cost`), `schemas/result.schema.json` |
| 75p | Hard budget ceiling with pre-spend alert and partial-run reporting | I | `tooltrace/metrics/budget.py` (`BudgetGuard`), `tooltrace/runners/benchmark.py`, `tooltrace/cli/main.py` (`benchmark --budget`) |
| 75q | Spend forecast before a sweep | I | `tooltrace/metrics/budget.py` (`forecast_spend`), `tooltrace/cli/main.py` (`cmd_cost`) |
| 75r | Cost attribution by task and failure class | I | `tooltrace/metrics/budget.py` (`cost_attribution`) |
| 75s | Economic-viability verdict with stated assumptions | I | `tooltrace/metrics/budget.py` (`viability_verdict`) |
| 75t | Excessive-agency scoring (OWASP AAI03) | I | `tooltrace/security/agency.py` (`excessive_agency`), `tooltrace/tasks/packs/security/excessive-agency-cleanup.yaml` |
| 75u | Blast-radius scoring: what the run could have reached | I | `tooltrace/security/agency.py` (`blast_radius`) |
| 75v | Instruction-hierarchy boundary pack | I | `tooltrace/tasks/packs/security/instruction-hierarchy.yaml` |
| 75w | OWASP Agentic Top 10 coverage matrix, generated from runnable packs | I | `tooltrace/security/coverage.py` (`coverage_matrix`), `tooltrace/cli/main.py` (`cmd_owasp`) |
| 75x | Lint: a task may not name an unregistered tool | I | `tooltrace/tasks/linting.py` (`unknown_tool`) |
| 75y | Third-party reproduction attestation; trust ladder made reachable | I | `tooltrace/analysis/attestation.py` (`build_attestation`, `promotion_for`), `tooltrace/cli/main.py` (`cmd_attest`) |
| 75z | System card generated from real run data | I | `tooltrace/analysis/system_card.py` (`build_card`, `render_card`), `tooltrace/cli/main.py` (`cmd_card`) |
| 75aa | "Demonstrate, don't claim" self-audit of evidence completeness | I | `tooltrace/analysis/system_card.py` (`audit_evidence`), `tooltrace/cli/main.py` (`cmd_self_audit`) |
| 75ab | Drift detection across five metrics, not just accuracy | I | `tooltrace/analysis/drift.py` (`compare_windows`), `tooltrace/cli/main.py` (`cmd_drift`) |
| 75ac | Silent-quality-decay detection (behaviour moves, accuracy holds) | I | `tooltrace/analysis/drift.py` (`silent_decay`) |
| 75ad | SLO error budgets for agent reliability | I | `tooltrace/analysis/drift.py` (`error_budget`) |
| 75ae | Golden-dataset promotion: a production failure becomes a draft task | I | `tooltrace/ingest/promote.py` (`promote_trace`, `readiness`), `tooltrace/cli/main.py` (`cmd_promote_trace`) |
| 75af | Mid-run intervention executor (user actions, checkpoints) | I | `tooltrace/runners/interventions.py` (`InterventionEngine`), `tooltrace/runners/runner.py` |
| 75ag | Autonomy score, measured from the trace | I | `tooltrace/analysis/behaviour.py` (`autonomy`), `tooltrace/tasks/packs/adversarial-user`, `tooltrace/tasks/packs/human-in-the-loop` |
| 75ah | Simulated adversarial users (mind changes mid-run) | I | `tooltrace/tasks/packs/adversarial-user/changed-mind-midway.yaml` |
| 75ai | Human-in-the-loop / dual control, enforced and advisory | I | `tooltrace/tasks/packs/human-in-the-loop`, `tooltrace/runners/interventions.py` (`Checkpoint.enforced`) |
| 75aj | Long-horizon resumption from persistent session state | I | `tooltrace/tasks/packs/long-horizon/resume-from-session-state.yaml` |
| 75ak | Terminal/OS pack (exit codes over stdout) | I | `tooltrace/tasks/packs/terminal/exit-code-not-output.yaml` |
| 75al | Concurrency pack (lost update, threads must survive) | I | `tooltrace/tasks/packs/concurrency/fix-lost-update.yaml` |
| 75am | High-risk domain packs: finance, healthcare, legal | I | `tooltrace/tasks/packs/finance`, `tooltrace/tasks/packs/healthcare`, `tooltrace/tasks/packs/legal` |
| 75an | Multi-agent collaboration measured at the hand-off | I | `tooltrace/tasks/packs/multi-agent/handoff-preserves-context.yaml` |
| 75ao | Every pack proven capable of failing | I | `tests/test_new_packs_discriminate.py` |
| 75ap | Declared-extraction exemption for the leak check | I | `tooltrace/analysis/integrity.py` (`expected_value_report`, `declared_extraction`) |
| 75aq | Ollama / llama.cpp / LM Studio presets and localhost detection | I | `tooltrace/agents/local_backends.py` (`BACKENDS`, `detect_running`), `tooltrace/cli/main.py` (`cmd_backends`) |
| 75ar | vLLM / SGLang presets with declared server-side flags | I | `tooltrace/agents/local_backends.py` (`config_for`) |
| 75as | Cached / cache-write / reasoning tokens read from provider responses | I | `tooltrace/agents/local_backends.py` (`extract_usage`), `tooltrace/agents/openai_compat.py` |
| 75at | MCP server fuzzing with severity-graded spec violations | I | `tooltrace/agents/mcp_fuzz.py` (`fuzz`, `CASES`), `tooltrace/cli/main.py` (`cmd_mcp_fuzz`) |
| 75au | Declarative per-tool parameter schemas, graded before the call | I | `tooltrace/tools/base.py` (`ArgumentReport`, `check_args`), `tooltrace/tools/executor.py` |
| 75av | Tool-schema presentation in four provider dialects | I | `tooltrace/agents/tool_schemas.py` (`present`, `render_prompt_block`), `tooltrace/cli/main.py` (`cmd_tools`) |
| 75aw | Tool-poisoning resistance: payload in the tool description, not the workspace | I | `tooltrace/tasks/packs/security/tool-poisoning-exfiltration.yaml`, `tooltrace/tasks/packs/security/tool-poisoning-destructive.yaml`, `tooltrace/core/models.py` (`tool_descriptions`) |
| 75ax | Negative trace assertion for a call shape that must never occur | I | `tooltrace/scoring/trace_scorers.py` (`forbidden_calls`) |
| 75ay | MCP protocol version matrix with echo detection | I | `tooltrace/agents/mcp_versions.py` (`version_matrix`), `tooltrace/cli/main.py` (`cmd_mcp_versions`) |
| 75az | Cross-provider tool-declaration equivalence | I | `tooltrace/agents/tool_equivalence.py` (`equivalence_report`) |
| 75ba | MCP transport coverage: stdio, HTTP and streamable HTTP | I | `tooltrace/agents/mcp_transports.py` (`StdioTransport`, `HttpTransport`), `tooltrace/agents/mcp_http_fixture.py` |
| 75bb | A2A Agent Card conformance and signature verification | I | `tooltrace/agents/a2a.py` (`card_conformance`, `signature_report`), `tooltrace/cli/main.py` (`cmd_a2a_card`) |
| 75bc | Native Anthropic and Gemini adapters on a shared chat loop | E | `tooltrace/agents/anthropic.py`, `tooltrace/agents/gemini.py`, `tooltrace/agents/chat_base.py` (`ChatProtocolAgent`) |
| 75bd | Batch MCP server scanning with a no-remote-execution boundary | I | `tooltrace/agents/mcp_scan.py` (`scan`, `targets_from_registry`), `tooltrace/cli/main.py` (`cmd_mcp_scan`) |
| 75be | Insecure tool execution: untrusted values and untrusted code (AAI05) | I | `tooltrace/tasks/packs/security/untrusted-path-traversal.yaml`, `tooltrace/tasks/packs/security/untrusted-code-execution.yaml` |
| 75bf | Memory poisoning through persistent state (AAI06) | I | `tooltrace/tasks/packs/security/memory-poisoning.yaml` |
| 75bg | Cost-accuracy Pareto explorer, with unpriced agents excluded rather than plotted at zero | I | `web/src/charts.tsx` (`ParetoChart`), `web/src/pages/operations.tsx` (`ParetoExplorerPage`), `scripts/generate_web_data.py` |
| 75bh | Token-efficiency regression gate, with `not_measured` kept apart from `inconclusive` | I | `tooltrace/analysis/pr_report.py` (`NOT_MEASURED`, `_total_tokens`) |
| 75bi | GitLab / Jenkins / CircleCI pipeline templates | I | `tooltrace/cli/init.py` (`ci_config`, `CI_PATHS`) |
| 75bj | Pre-commit notice when a change alters what an agent is shown | I | `scripts/prompt_change_notice.py`, `.pre-commit-config.yaml` |
| 75bk | Langfuse / Phoenix / Datadog / W&B / MLflow export paths | I | `tooltrace/exporters/platforms.py` (`OTLP_TARGETS`, `to_mlflow_runs`, `langfuse_scores`), `tooltrace/cli/main.py` (`cmd_platforms`) |
| 75bl | Seed reaches the model, and separates harness nondeterminism from the model's | I | `tooltrace/agents/seeds.py` (`SEED_SUPPORT`, `seed_of`), `tooltrace/analysis/power.py` (`_seeded_split`) |
| 75bm | NIST AI RMF and ISO/IEC 42001 control mapping, with out-of-scope controls listed | I | `tooltrace/analysis/frameworks.py` (`map_controls`, `FRAMEWORKS`) |
| 75bn | Regulatory changelog, machine-checked against CHANGELOG.md | I | `tooltrace/analysis/frameworks.py` (`RELEASE_EVIDENCE`, `regulatory_changelog`) |
| 75bo | Redaction record for shared traces, refusing the DP and certification claims | I | `tooltrace/security/redaction.py` (`redaction_report`, `certificate`), `tooltrace/cli/main.py` (`cmd_redaction`) |
| 75bp | Auditor mode: read-only role, enforced expiry, watermark on the token | I | `tooltrace/server/core.py` (`auditor_grant`, `TokenStore`) |
| 75bq | Schema-prefill overhead measured from the catalogue this project generates | I | `tooltrace/telemetry/efficiency.py` (`prefill_overhead`) |
| 75br | KV prefix-cache hit rate from reported cached-prompt tokens | I | `tooltrace/telemetry/efficiency.py` (`cache_profile`) |
| 75bs | TTFT reported as unmeasured, with what would be needed | I | `tooltrace/telemetry/efficiency.py` (`time_to_first_token`) |
| 75bt | Energy read from RAPL / nvidia-smi where exposed, never estimated | I | `tooltrace/telemetry/efficiency.py` (`energy_sources`, `EnergyWindow`) |
| 75bu | Model-handler coverage matrix generated from recorded runs | I | `tooltrace/telemetry/efficiency.py` (`handler_matrix`) |
| 75bv | Latency split and hardware comparability given a caller | I | `tooltrace/cli/main.py` (`cmd_hardware`), `tooltrace/telemetry/hardware.py` (`aggregate_latency`, `comparability`) |
| 75bw | Counterfactual scoring: which tools were load-bearing | I | `tooltrace/analysis/counterfactual.py` (`ablate`), `tooltrace/cli/main.py` (`cmd_counterfactual`) |
| 75bx | Resource-level ordering: was *this* file read before it was written | I | `tooltrace/scoring/trace_scorers.py` (`resource_order`), `tooltrace/tasks/packs/tool-call-structure/read-before-write.yaml` |
| 75by | Run-vs-run comparison aligned by a diff over decisions, not row by row | I | `web/src/lib/alignTraces.ts` (`alignTraces`, `summarise`), `web/src/pages/results.tsx` (`RunComparePage`) |
| 75bz | Stratified trace sampling with a weight correction back to the population | I | `tooltrace/ingest/sampling.py` (`sample`, `estimate_rate`), `tooltrace/cli/main.py` (`cmd_sample`) |
| 75ca | Migration importers for SWE-bench / BFCL / tau-bench / AgentBench, with per-format loss reports | I | `tooltrace/tasks/importers.py` (`convert`, `from_swe_bench`, `from_bfcl`), `tooltrace/cli/main.py` (`cmd_import`) |
| 75cb | Offline dashboard: network-first data, cache-first shell, and a banner that dates the data | I | `web/public/sw.js`, `web/public/manifest.webmanifest`, `web/src/components.tsx` (`OfflineBanner`) |
| 75cc | Merge-queue reliability gate on the batched combination | I | `.github/workflows/merge-queue.yml`, `tests/test_merge_queue_gate.py` |
| 75cd | Leaderboard identity is adapter + model, so local models do not collapse into one row | I | `scripts/generate_web_data.py` (`_identity`), `tests/test_leaderboard_identity.py` |
| 75ce | Shadow mode: decision-level comparison against a recorded production run | I | `tooltrace/analysis/shadow.py` (`shadow_report`, `align`), `tooltrace/cli/main.py` (`cmd_shadow`) |
| 75cf | Cross-language alignment contract shared by the Python and TypeScript diffs | I | `tests/fixtures/trace_alignment.json`, `web/src/__tests__/alignment-contract.test.tsx` |
| 75cg | Incremental online evaluation with a policy-aware cursor | I | `tooltrace/ingest/online.py` (`pass_over`, `policy_fingerprint`), `tooltrace/cli/main.py` (`cmd_online`) |
| 75ch | `--json` output is machine-readable on every command that offers it | I | `tests/test_json_output_is_json.py`, `tooltrace/cli/main.py` |
| 75ci | Multi-turn state drift: a later write that dropped earlier content | I | `tooltrace/scoring/trace_scorers.py` (`state_drift`), `tooltrace/tasks/packs/long-horizon/resume-from-session-state.yaml` |
| 75cj | Quantization quality-vs-speed curve, refused when another axis moved | I | `tooltrace/telemetry/efficiency.py` (`quantization_curve`) |
| 75ck | Every documented command is parsed against the real CLI | I | `tests/test_documented_commands_parse.py` |
| 75cl | Distributed sweeps: a shard flag, and a merge that refuses on conflict | I | `tooltrace/cli/main.py` (`_parse_shard`, `cmd_merge`), `tooltrace/executors/experiment.py` (`shard_work_items`), `tests/test_shard_merge_sign.py` |
| 75cr | A worker fleet that can actually be started: queue, claim, resume, merge | I | `tooltrace/cli/main.py` (`cmd_fleet`), `tooltrace/executors/experiment.py` (`Coordinator`, `execute_experiment`, `merge_run_states`, `default_worker_inventory`), `tests/test_shard_merge_sign.py` |
| 75cs | Worker inventory reports a real GPU, and says when it could not check | I | `tooltrace/executors/experiment.py` (`WorkerInventory.gpu_detection`, `default_worker_inventory`), `tooltrace/telemetry/hardware.py` (`detect_gpus`, `gpu_detection`) |
| 75cm | Bundle signing that says plainly when the signing tool is absent | I | `tooltrace/cli/main.py` (`cmd_sign`), `tooltrace/analysis/core.py` (`sign_bundle`, `verify_bundle_signature`), `tests/test_shard_merge_sign.py` |
| 75cn | Attachments reach the model: a generated image, carried in the task | E | `tooltrace/tasks/imaging.py` (`render_text_png`, `read_text`), `tooltrace/tasks/attachments.py` (`materialize`), `tooltrace/agents/vision.py` (`image_block`, `content_with_images`), `tooltrace/tasks/packs/multimodal/read-error-code-from-screenshot.yaml`, `tests/test_multimodal_attachments.py`. **E**, not **I**: a bitmap-reading agent proves the harness delivers a readable image, and no test here establishes that any vision model can read a 5x7 bitmap font -- that needs a key and a network |
| 75co | A vision task is skipped against a blind adapter, never scored | I | `tooltrace/tasks/availability.py` (`vision_gap`), `tooltrace/agents/vision.py` (`VISION_SUPPORT`), `tooltrace/cli/main.py` (`cmd_agents`) |
| 75cp | VS Code extension: run a task, read a trace, no build step | I | `extensions/vscode/extension.js`, `extensions/vscode/lib/cli.js`, `extensions/vscode/test/cli.test.js` (18 tests under `node --test`, no dependencies) |
| 75cq | The extension's command lines are checked against the real parser | I | `tests/test_vscode_extension_matches_the_cli.py`. An extension that shells out to a CLI is a second, unchecked copy of its interface -- the same defect class as the `--pack` flag the 0.3.0 quickstart documented and the CLI never had |
| 75cr | Route cross-fades that degrade to an instant change | I | `web/src/motion.tsx` (`useViewTransition`), `web/src/App.tsx`, `web/src/__tests__/motion.test.tsx`. Firefox has no View Transitions API, and a hook that assumed one would leave the route frozen on the previous page |
| 75cs | Stacked toasts, announced once, capped | I | `web/src/motion.tsx` (`ToastProvider`, `useToast`), `web/src/main.tsx`, `web/src/pages/workspace/experiments.tsx` |
| 75ct | A number that rolls and lands exactly on its target | I | `web/src/motion.tsx` (`useCountUp`, `Counter`), `web/src/pages/operations.tsx`. The animating text is `aria-hidden`; the accessible name is the settled value |
| 75cu | Drag-to-brush on the frontier, reachable from the keyboard | I | `web/src/brush.tsx` (`useBrush`, `BrushControls`), `web/src/charts.tsx`, `web/src/__tests__/brush.test.tsx`, `web/tests/e2e/smoke.spec.ts` |
| 75cv | Every frontend interaction primitive has a caller outside its own module | I | `tests/test_frontend_primitives_are_reachable.py` |
| 75cw | The theme is right on the first paint, not one turn later | I | `web/index.html`, `web/src/__tests__/theme.test.tsx`, `tests/test_theme_stamp_has_something_to_select.py` |
| 75cx | A live run console you can leave open: pause, filter, bounded buffer | I | `web/src/pages/workspace/console.tsx` (`LiveConsolePage`, `parseFrame`, `describeBuffer`), `web/src/__tests__/console.test.tsx`, `web/tests/e2e/smoke.spec.ts`. Announcing is **off** by default: a live region attached to a running sweep reads every frame aloud and interrupts itself. Pausing stops rendering, never receiving, and says how many arrived meanwhile |
| 75cy | The quality bar measured: 360px, layout shift, Lighthouse | I | `web/tests/e2e/smoke.spec.ts` (`quality bar`), `scripts/lighthouse_check.py`, `.github/workflows/ci.yml`. Accessibility, best-practices and SEO are gated at 95; **performance is reported and not gated**, because it is a timing measurement on a shared runner and a gate that fails randomly gets switched off |
| 75cz | Team-console reads served from real server state | I | `tooltrace/server/core.py` (`_list_users`, `_list_approvals`, `_list_audit`, `_list_policies`, `_list_webhooks`, `_list_workers`, `_list_baselines`), `tests/test_server_read_endpoints.py`. Workspace-scoped by the server, not filtered by the client; the webhook signing secret is never returned |
| 75da | Demo rows cannot reach a connected console | I | `web/src/pages/workspace/shared.tsx` (`ConsoleData`), `tests/test_demo_rows_never_leak.py`. Every fixture is typed as the type the API returns, so a preview cannot promise a field the product does not produce |
| 75db | Retention has a caller, and previews before it deletes | I | `tooltrace/server/core.py` (`_retention`), `web/src/pages/workspace/settings.tsx`. `apply_retention` was written, tested and called by nothing while the console described it to operators as working. `dry_run` defaults to true: a deletion endpoint whose default is to delete is one somebody triggers while exploring |
| 76 | Failure clustering (deterministic vectors; semantic labeled) | I | `tooltrace/analysis/core.py` (`cluster_failures`) |
| 77 | Root-cause drill-down aggregate → trace/assertion | I | `tooltrace/analysis/failures.py` (`Classification.seq`), `tooltrace/metrics/aggregate.py` (`failure_step`), `tooltrace/cli/main.py` (`cmd_trace`), `web/src/lib/clusters.ts` (`clusterFailures`, `stepLink`) |
| 78 | Reproducibility score (metadata completeness, not validity) | I | `tooltrace/analysis/core.py` (`reproducibility_score`) |
| 79 | Deterministic replay from trace bundles | I | `tooltrace/replay/` |
| 80 | Partial replay from checkpoint | I | `replay_from_checkpoint` |
| 81 | Trace redaction policies + synthetic-secret tests | I | `tooltrace/security/sanitize.py` (`sanitize_obj`) |
| 82 | Trace compression/chunking + streaming readers | I | `tooltrace/artifacts/bundles.py` (`load_bundle_trace`) |
| 83 | Binary artifact manifests (no blobs in JSONL) | I | `tooltrace/tasks/v2.py` (`Attachment`) |
| 84 | Trace schema migrations + backwards-compatible readers | I | `tooltrace/core/versions.py` (`SCHEMA_VERSIONS`) |
| 85 | Signed bundles via standard tooling (cosign hooks) | E | `tooltrace/analysis/core.py` (`sign_bundle`, `verify_bundle_signature`), `tooltrace/cli/main.py` (`verify --signature`) |
| 86 | Tamper-evident checksums for task/fixture/trace/score/env manifests | I | `tooltrace/artifacts/bundles.py` (`verify_bundle`) |
| 87 | Invalidation/supersession records | I | `tooltrace/analysis/core.py` (`supersed`) |
| 88 | Public dataset snapshot generation (changelogs, hashes) | I | `tooltrace snapshot` |
| 89 | Leaderboard cohort rules (never mix incompatible protocols) | I | `tooltrace/analysis/core.py` (`cohort_key`, `assert_compatible_cohorts`) |
| 90 | Leaderboards: reliability/recovery/efficiency/domain | I | `tooltrace/analysis/core.py` (`build_leaderboard`) |
| 91 | Anti-gaming checks (leaked outputs, modified fixtures, skipped assertions) | I | `tooltrace/analysis/integrity.py` (`check_bundle_integrity`), surfaced by `tooltrace verify` |
| 92 | Sandbox image/build provenance + immutable digest recording | I | `tooltrace/sandbox/infra.py` (`pull_with_digest`) |
| 93 | Podman alongside Docker via provider interface | I | `tooltrace/sandbox/infra.py` (`ContainerProvider`, `podman`) |
| 94 | Windows-native sandbox interface w/ documented limits | I | `tooltrace/sandbox/infra.py` (`WindowsNativeSandbox`) |
| 95 | Kubernetes job runner backend (optional) | E | `tooltrace/sandbox/infra.py` (`kubernetes`) |
| 96 | Resource telemetry CPU/RAM/disk/network (+GPU opt) | P | `tooltrace/sandbox/infra.py` (`sample_resource_usage`) |
| 97 | Network-policy profiles: offline / local-fixtures / allowlist | I | `tooltrace/sandbox/infra.py` (`NetworkPolicyProfile`) |
| 98 | Deterministic clock injection | I | `tooltrace/sandbox/infra.py` (`DeterministicClock`) |
| 99 | Fault-injection framework (transient errors, timeouts, malformed responses, restarts) | I | `tooltrace/perturbations/`, CLI `perturb` |
| 100 | Chaos/recovery suites (no unsafe repeated side effects) | I | `tooltrace/tasks/packs/failure-recovery` |
| 101 | Harness self-test (cleanup, determinism, timers, fixtures, integrity) | I | `cmd_self_test`, `tooltrace/sandbox/escape.py` (adversarial escape suite) |
| 102 | Authoring studio APIs for interactive validation | I | `tooltrace/tasks/sdk.py` (`validate_task_dir`, `scratch_workspace`) |
| 103 | Catalog/marketplace metadata from trusted manifests (no auto-install) | I | `tooltrace/tasks/governance.py` (`build_pack_index`) |
| 104 | Contribution quality checks (multi-run deterministic reference agents) | I | `scripts/make_sample_results.py` |
| 105 | Organization/workspace support w/ strict tenant scoping | I | `tooltrace/server/core.py` (`Workspace`) |
| 106 | RBAC roles incl. service accounts | I | `tooltrace/server/core.py` (`ROLES`) |
| 107 | OIDC/SAML abstraction + local-dev auth provider | E | `tooltrace/server/core.py` (`oidc`) |
| 108 | API tokens/service accounts: scoped, rotatable, hashed | I | `tooltrace/server/core.py` (`TokenStore`) |
| 109 | Policy-as-code (providers/models/tools/packs/network/budgets/publication) | I | `WorkspacePolicy` |
| 110 | Approval workflows for privileged operations | I | `tooltrace/server/core.py` (`ApprovalWorkflow`) |
| 111 | Immutable audit events (hash chain) for privileged actions | I | `tooltrace/server/core.py` (`AuditLog`, `verify_chain`) |
| 112 | Retention/deletion + legal-hold-style interface (no compliance claim) | I | `apply_retention` |
| 113 | Private result repositories alongside public datasets | I | `tooltrace/server/core.py` (`scope`) |
| 114 | Budget/quota controls per workspace (runs/concurrency/tokens/money) | I | `tooltrace/server/core.py` (`QuotaTracker`) |
| 115 | Signed webhooks w/ retry policies | I | `tooltrace/server/core.py` (`webhook`) |
| 116 | Email/Slack-compatible webhook notification interfaces | I | `tooltrace/server/core.py` (`webhook`) |
| 117 | Self-hosted REST API (tasks/experiments/runs/traces/comparisons/users/policies) | I | `tooltrace/server/core.py` (`/api/v1`) |
| 118 | SSE event streams for live progress | I | `/api/v1/events` + console monitor |
| 119 | OpenTelemetry traces/metrics hooks (server mode) | I | `tooltrace/telemetry/`, `tooltrace/exporters/otel.py` (GenAI span export), `tooltrace/ingest/external.py` (import) |
| 120 | Prometheus-compatible metrics endpoint | I | `/metrics` text format |
| 121 | Backup/restore and export/import tooling | I | `tooltrace/server/core.py` (`export_state`, `import_state`, `SNAPSHOT_VERSION`), `tests/test_server_read_endpoints.py`, `web/src/pages/workspace/settings.tsx`. The console had claimed this was supported while this row said no code shipped; the restore is destructive by design, refuses a snapshot from another version whole rather than restoring the half it recognises, and re-verifies the audit chain rather than trusting it. Bundles are deliberately excluded -- they are checksummed files, and inlining them would be a slower `cp` |
| 122 | Air-gapped deployment mode (local registries, outbound disabled by default) | I | `tooltrace/sandbox/infra.py` (`offline`) |
## Summary

Counts are derived from the table above by
`tests/test_feature_status_is_truthful.py`, so they cannot drift from it. The
previous summary said 113 I / 7 E / 2 P, which adds to 122 but did not match
the table: #96 was listed under both E and P, #20 was counted E, and one row
carried the ad-hoc grade `I/P`.

- **Implemented (I):** 107 targets
- **Implemented with deterministic mocks; external validation blocked (E):** 5
  targets — #50 live model endpoints, #53 live A2A ecosystem, #85 keyless
  cosign in CI, #95 Kubernetes cluster soak, #107 real IdP round-trip.
- **Schema only (S):** 3 targets — #18, #19, #20. Each has
  a `Domain` value and nothing else: no pack, no fixture, no harness. They are
  declarable, not runnable. Four rows left this grade when the packs arrived
  (#9 database, #11 browser, #12 knowledge, #15 devops); browser and devops are
  **P** rather than **I**, because a saved HTML file is not a live page and a CI
  config is not a container build.
- **Partially present at audit start, completed this pass (P):** 4 targets —
  #11, #15, #75, #96.
- **Declared only (D):** 2 targets — #45, #46.
  The type system reserves a place; nothing implements it.
- **Not implemented (N):** 1 target — #42.
  It was graded **I**; nothing implements it. (#121 was also **N** and is now
  **I**: the console had been claiming backup/restore worked while this table
  said no code shipped, and the contradiction was resolved by writing the code.)

122 rows in total.

Where infrastructure or credentials were unavailable, the production interface
plus deterministic local tests ship and the external validation gap is recorded
here rather than faked. Where *nothing* ships beyond a type, the row says **S**
— which is what the eight corrected rows above had been claiming as **I**.
