# Recipes

Copy-paste workflows for common evaluation goals. All commands work offline
unless explicitly noted; deterministic results come from the bundled scripted
agents and local fixtures.

## 1. Sanity-check a new agent adapter

```bash
tooltrace doctor                       # environment + discovered plugins
tooltrace run --task fileops/copy-and-rename --agent my_adapter --json
tooltrace reproduce runs/<latest>.tooltrace
```

## 2. Reliability benchmark (pass^k / pass@k)

```bash
tooltrace benchmark --pack fileops --agent scripted --runs 5 --json
```

Read `pass^k` as "probability that k consecutive attempts all succeed" — the
consistency metric most benchmarks omit.

## 3. Failure-recovery measurement

```bash
# Task-declared perturbations, 3 repetitions:
tooltrace perturb --task failure-recovery/retry-after-tool-failure \
  --agent scripted --runs 3 --summary --json

# Inject an extra fault kind on any task:
tooltrace perturb --task file-editing/fix-config-typo \
  --perturbation tool_failure:read_file --runs 3
```

Recovery metrics distinguish transient tool failures from agent-caused
failures; `--min-recovery-rate` gives a CI gate a stable exit code.

## 4. Fair two-agent comparison

```bash
tooltrace showdown --agent-a scripted --agent-b subprocess \
  --suite fileops-core --reps 3 --json
```

Showdown refuses incompatible task/protocol/scorer cohorts; paired-run
analysis is used when identical seeds exist for both candidates.

## 5. CI regression gate

```bash
# In your pipeline, after generating fresh bundles:
tooltrace baseline --suite fileops-core --from runs/
tooltrace regression --baseline .tooltrace-baselines.json --suite fileops-core
```

Exit codes are stable: non-zero on regression beyond configured tolerance at
suite/domain/task/metric level.

## 6. Authoring a deterministic task pack

```bash
tooltrace task scaffold --id mypack/new-task --out tooltrace/tasks/packs
tooltrace validate --path tooltrace/tasks/packs/mypack
tooltrace lint --path tooltrace/tasks/packs/mypack
tooltrace dry-run --task mypack/new-task     # no model required
```

Or draft interactively in the web console: **Workspace → Studio**.

## 7. Team evaluation on your own workers

```bash
tooltrace server &                          # coordinator + REST/SSE API
# open the console → Workspace → Experiments → New experiment
```

RBAC, quotas, approvals and audit apply per workspace; see
[enterprise-deployment.md](enterprise-deployment.md).

## 8. Publishing a trustworthy dataset snapshot

```bash
python scripts/make_sample_results.py       # real, reproducible bundles
tooltrace snapshot --out data/snapshots     # hashes, counts, changelog
tooltrace snapshot --verify                 # integrity check
```

## 9. Inspecting why a run failed

```bash
# Terminal: verify checksums, list events, filter, show assertions only.
tooltrace trace runs/<bundle>.tooltrace --limit 20
tooltrace trace runs/<bundle>.tooltrace --filter read_file
tooltrace trace runs/<bundle>.tooltrace --assertions --json

# Or use Trace Explorer in the web UI: filter by type/tool/failure,
# expand sanitized payloads, jump between events, download raw JSONL.
