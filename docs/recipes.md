# Recipes

Copy-paste workflows for common evaluation goals. All commands work offline
unless explicitly noted; deterministic results come from the bundled scripted
agents and local fixtures.

## 1. Sanity-check a new agent adapter

```bash
tooltrace doctor                       # environment + discovered plugins
tooltrace run --task file-editing/fix-config-typo --agent my_adapter --json
tooltrace reproduce runs/<latest>.tooltrace
```

## 2. Reliability benchmark (pass^k / pass@k)

```bash
tooltrace benchmark --task file-editing/fix-config-typo,bug-fixing/fix-off-by-one --agent scripted --runs 5 --json
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
tooltrace showdown --agents scripted,subprocess \
  --task file-editing/fix-config-typo --runs 3 --json
```

`--agents` takes a comma-separated list. Showdown refuses incompatible
task/protocol/scorer cohorts; paired-run analysis is used when identical seeds
exist for both candidates.

## 5. CI regression gate

```bash
# In your pipeline, after generating fresh bundles:
tooltrace baseline --name nightly --bundle runs/<baseline-bundle>.tooltrace
tooltrace regression \
  --baseline runs/<baseline-bundle>.tooltrace \
  --current  runs/<current-bundle>.tooltrace \
  --thresholds '{"score":{"min_delta":-0.05}}'
```

`--baseline` and `--current` are bundle directories, and `--thresholds` is
inline JSON rather than a file path. `regression` exits non-zero when a
threshold is breached, so it gates a pipeline directly.

## 6. Authoring a deterministic task pack

```bash
tooltrace task scaffold --pack-dir tooltrace/tasks/packs --task-id mypack/new-task
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
tooltrace snapshot --source results --output data/snapshots/index.json --changelog "nightly"
tooltrace snapshot --source results --output data/snapshots/index.json --verify
```

## 9. Inspecting why a run failed

```bash
# Terminal: verify checksums, list events, filter, show assertions only.
tooltrace trace runs/<bundle>.tooltrace --limit 20
tooltrace trace runs/<bundle>.tooltrace --filter read_file
tooltrace trace runs/<bundle>.tooltrace --assertions --json

# Or use Trace Explorer in the web UI: filter by type/tool/failure,
# expand sanitized payloads, jump between events, download raw JSONL.


## Gate a pull request on agent reliability

The published composite action runs a trimmed benchmark and fails the step when
the success rate drops below a floor. It installs no third-party actions, so set
up Python with whatever pinning policy your repository already applies.

```yaml
name: Agent reliability
on: [pull_request]

jobs:
  reliability:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: webdevsamran/tooltrace-bench@v0.3.0
        with:
          agent: scripted
          runs: "3"
          limit: "8"
          shuffle: "true"
          seed: "0"
          min-success-rate: "0.9"
```

`limit` is what makes this affordable on every pull request. The selection is
recorded rather than silently cut: the job summary states how many of how many
tasks ran, under which policy and seed, so a trimmed run is never mistaken for a
full one, and the same seed selects the same tasks next time.

The step warns when a threshold is met by a small sample. A success rate of 1.0
over three runs has a wide confidence interval, and a green check should not
imply more evidence than was collected.

The equivalent by hand, if you would rather not use the action:

```bash
tooltrace benchmark --agent scripted --runs 3 --limit 8 --shuffle --seed 0 --min-success-rate 0.9 --json
```
