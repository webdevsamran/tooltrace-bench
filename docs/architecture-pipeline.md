# Architecture — Final Pipeline

```
Task/Pack ──► Experiment ──► Scheduler ──► Agent Adapter ──► Sandbox/Tools
                                                                │
                                                                ▼
                              Result Bundle ◄── Scorers ◄──── Trace
                                   │
                                   ▼
                    Compare / Regression ──► Dataset/UI
                                   ▲
        Coordinator/Workers (optional, team mode) ┘
```

## Stages

1. **Task/Pack** — versioned YAML packs (`protocol: 2`) with provenance manifests,
   fixture hashes, contamination flags, prerequisites/budgets. Validated by
   `tooltrace lint` and `dry-run`.
2. **Experiment** — manifest pinning suite, adapter, model metadata, sampling,
   repetitions, sandbox profile, scorer versions.
3. **Scheduler** — local bounded-concurrency runner; optional coordinator with
   registered workers, resumable checkpoints, sharding/merge, fairness queues.
4. **Agent Adapter** — OpenAI-/Anthropic-/Gemini-compatible and local subprocess
   adapters; MCP client support; capability negotiation; retry/backoff recorded
   in traces; secret-safe credential resolution.
5. **Sandbox/Tools** — temp-workspace (default), Docker/Podman providers,
   Windows-native interface; network profiles offline/local-fixtures/allowlist;
   fault injection for recovery suites.
6. **Trace** — append-only JSONL events with schema version, redaction policies,
   chunked streaming readers, binary artifact manifests.
7. **Scorers** — deterministic assertions first; outcome-vs-trajectory dual
   scoring; optional judges with disagreement reporting and calibration sets.
8. **Result Bundle** — `.tooltrace` directory with checksums, reproducibility
   score inputs, signing support via standard tooling.
9. **Compare/Regression** — cohort-safe comparisons (protocol/scorer/task
   compatibility enforced), baselines, trends, significance where justified.
10. **Dataset/UI** — generated validated indexes → static frontend; server mode
    exposes the same data over REST/SSE.

Protocol v1 → v2 migration is backwards-compatible: old bundles remain readable;
new fields are additive. See `schemas/` for canonical schemas.