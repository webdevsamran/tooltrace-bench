# Contributing to ToolTrace Bench

Thank you for considering a contribution. ToolTrace Bench is a reliability laboratory — precision and honesty matter more than volume.

## Ground rules

- **Never fabricate results.** No invented benchmark numbers, agents, companies, users, certifications or partnerships. Frontend data comes only from validated bundles.
- **Determinism first.** New tasks must be CI-safe: no network, no wall-clock dependence, no flaky assertions.
- **Typed code.** Python 3.11+, full type annotations, `mypy --strict` clean.
- **Tests required.** Every feature lands with tests. Bug fixes land with a regression test.
- **No `|| true`.** CI failures are real failures.

## Development setup

```bash
git clone https://github.com/webdevsamran/tooltrace-bench.git
cd tooltrace-bench
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

## Workflow

1. `main` is the only permanent branch. Branch from it (e.g. `feat/my-task-pack`).
2. Make focused changes; keep commits logical.
3. Run locally before pushing:
   ```bash
   ruff check tooltrace tests && ruff format --check tooltrace tests
   mypy
   pytest --cov=tooltrace
   tooltrace validate schemas/ tooltrace/tasks/packs/
   ```
4. Open a PR against `main` with a clear description of *what* and *why*.
5. Maintainers reconcile and squash-reconcile into `main`; obsolete branches are deleted after merge. History is never rewritten or force-pushed.

## What to contribute

See the issue tracker for scoped, meaningful issues:

| Area | Examples |
|---|---|
| Task packs | new deterministic tasks in existing categories; new categories |
| Adapters | local agent runtimes, additional OpenAI-compatible quirks |
| Deterministic scorers | AST checks, git-diff constraints, API-state checks |
| Sandboxes | Docker hardening, OS-specific isolation |
| Frontend | trace timeline UX, diff viewer, accessibility |
| Analysis | statistics, failure-classification heuristics |

Please avoid trivial issue spam ("fix typo" issues without substance).

## Adding a task pack

```bash
tooltrace task scaffold mypack --dir tooltrace/tasks/packs
# edit the generated YAML + fixtures
tooltrace task validate tooltrace/tasks/packs/mypack
tooltrace task test tooltrace/tasks/packs/mypack   # runs with scripted agent
```

## Code style

- Formatting/linting: `ruff format` + `ruff check`
- Types: `mypy` (strict)
- Commits: imperative mood, e.g. `Add recovery-rate metric to benchmark runner`

## Reporting bugs

Open an issue using the bug template. Include: command, `--json` output, bundle path if available, OS/Python versions. Never paste secrets — traces are sanitized, but double-check.

## License

By contributing you agree your contributions are licensed under Apache-2.0.