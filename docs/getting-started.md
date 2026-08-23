# Getting Started

## Requirements

- Python 3.11+ (3.12/3.13 tested in CI)
- Optional: Docker or Podman for containerized sandboxes; Node 20+ for the frontend

## Install

```bash
git clone https://github.com/webdevsamran/tooltrace-bench.git
cd tooltrace-bench
pip install -e ".[dev]"
```

## First run (no model needed)

The bundled `scripted` agent replays deterministic tool-call scripts, so you can
validate your install without any provider credentials:

```bash
tooltrace doctor                 # environment + registry health
tooltrace tasks                  # list bundled tasks
tooltrace dry-run --task file-editing/fix-config-typo   # validate task w/o model
tooltrace self-test              # harness integrity: cleanup/determinism/timers
tooltrace run --task file-editing/fix-config-typo --agent scripted
```

Each run writes a `.tooltrace` bundle with `result.json`, `trace.jsonl`,
`task.yaml`, `environment.json`, `workspace.diff`, `scoring.json` and checksums.

## First reliability benchmark

```bash
tooltrace benchmark --agent scripted --runs 3 --summary
tooltrace perturb --help         # inject safe transient failures, measure recovery
tooltrace showdown --agents scripted,scripted --runs 2   # fair comparison cohorts
```

## Inspect results

```bash
tooltrace report --bundles runs --format html --output report.html
tooltrace reproduce runs/<bundle>.tooltrace --no-rerun   # verify hashes
```

Or open the frontend:

```bash
cd web && npm ci && npm run build
tooltrace serve --dir web/dist   # http://127.0.0.1:8000
```

## Next steps

- Author a pack: `tooltrace task scaffold --pack-dir my-pack --task-id my-task`
- Lint it: `tooltrace lint --path my-pack`
- Team mode: see [Self-hosting](self-hosting.md).