# AGENTS.md

Working notes for AI coding agents in this repository. Everything here is
checked against CI — if a command below disagrees with
`.github/workflows/ci.yml`, the workflow wins and this file is the bug.

## What this project is

`tooltrace` benchmarks AI agents on real tasks and publishes numbers. That
makes it a measurement instrument, and a measurement instrument's only asset
is that its numbers can be checked. Every number this repository prints must
be traceable to a committed artifact produced by a deterministic run — not to
a plausible-looking example.

That is not an abstract principle here. The README once carried a section
headed *"A real sample run"*, prefaced *"no fabricated numbers"*, showing
output for `fileops/copy-and-rename` — a task that does not exist — with score
components no scorer emits and a `wall_ms` traceable to `web/src/pages/demoData.ts`.
`tests/test_readme_is_truthful.py` exists so that cannot recur, and
`tests/test_feature_status_is_truthful.py` does the same for
`docs/feature-status.md`, which had graded eight unbuilt capabilities as
implemented.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

Python 3.11 is the floor. Lint, types and coverage run on ubuntu/3.12; the
suite also runs on windows and macOS, and on 3.11/3.13/3.14, matching the
classifiers in `pyproject.toml`. Node 22 for the frontend.

## Commands CI runs

```bash
ruff check tooltrace scripts tests
ruff format --check tooltrace scripts tests
mypy tooltrace
pytest --cov=tooltrace --cov-report=term-missing --cov-fail-under=80
python scripts/make_sample_results.py
python scripts/cli_smoke.py
python scripts/sandbox_check.py
python scripts/secret_scan.py
python scripts/check_docs_links.py
python scripts/generate_web_data.py
pip-audit            # "Dependency audit (blocking)"
cd web && npm ci && npm run lint && npm run build && npm test && npm run test:e2e
```

`fail_under = 80` is in `pyproject.toml` as well as on the CI command line,
so a local `pytest --cov` enforces the same floor.

## Rules that are not style preferences

**Published numbers reconcile to a committed bundle.** Anything unmeasured
reads as null; it is never interpolated, and never borrowed from a demo
fixture. If a documented command does not produce the documented output, the
fix is the code or the doc — not a nicer-looking number.

**Status documents are machine-checked.** `docs/feature-status.md` grades 122
capability targets. `I` means implemented with code and tests; `S` means the
type system admits it and nothing ships. A row that cites a path must have
that path; a row claiming a task pack must have that pack directory; the
summary counts are derived from the table. Grade honestly and the tests pass.

**The agent never touches the host.** It acts through the typed tool registry
in `tooltrace/tools/`, inside a sandbox workspace, with network denied at the
tool layer unless explicitly allowlisted. Anything that would let a task
escape that boundary is a security change, not a feature — `docs/threat-model.md`
records what is and is not enforced, and it must not assert isolation the
conformance suite does not test.

**Scorers are deterministic and read artifacts, not narration.** Scoring looks
at the trace and the final workspace, never at the agent's own account of what
it did. A scorer that consults a model belongs behind a judge adapter that
declares the dependency.

**Subprocesses do not inherit this run's coverage plumbing.** `tooltrace/tools/process.py`
and `tooltrace/scoring/builtin.py` strip `COV_CORE*`, `COVERAGE*` and
`PYTEST_*` before spawning. A child that starts coverage in a directory
without `pyproject.toml` records statement-only data, and combining that with
the parent's branch data aborts the whole pytest session.

**The SBOM describes this project, not this machine.** `scripts/generate_sbom.py`
resolves the closure of what `pyproject.toml` declares. It used to iterate
`importlib.metadata.distributions()`, which listed 147 components against six
declared dependencies — including two unrelated sibling projects, named as
`pkg:pypi/` dependencies of this one. `tests/test_sbom_is_honest.py` covers it.

## Do not touch without being asked

- **Workflow job names in `.github/workflows/ci.yml`.** Branch protection
  matches required contexts byte-for-byte. This repository has already spent a
  backlog in that state: the jobs were renamed to `Dependency audit (blocking)`
  and `Frontend lint · typecheck · test · build · e2e · a11y` while protection
  still required the old names, so no pull request could merge at all. The
  `python-versions` job carries a comment explaining why it is a separate job
  rather than a dimension on `python-matrix` — that reasoning is load-bearing.
- `tooltrace/tasks/v2.py` — the task protocol is versioned; v1 migrates
  forward, so changing a field means a migration, not an edit.
- The `.tooltrace` bundle layout and `EvalResult` — consumed by
  `analysis/`, `replay/` and the frontend.

## Conventions

Conventional commits with scopes (`fix(scoring): make data_equals
order-insensitive`). Typed Python; `mypy` must pass clean. `main` is the only
permanent branch.
