# Troubleshooting & FAQ

## Common problems

**`tooltrace: command not found` after install**
Use `python -m tooltrace.cli.main` or re-run `pip install -e .` inside the repo.

**Docker sandbox unavailable**
Container sandboxes are optional. The default `TempWorkspaceSandbox` /
Windows-native sandbox needs no daemon. Check `tooltrace doctor`.

**A task fails lint with `unreachable_assertion`**
The assertion targets a path not present in fixtures nor clearly creatable by
the allowed tools. Either add the fixture, declare the side effect, or fix the
assertion target.

**Regression gate exits 8**
That is the designed CI failure code when thresholds are violated. Inspect the
JSON report for the offending metric deltas.

**Server returns 403**
Tokens are workspace-scoped. Ensure the token owner's user exists in
`STATE.users` for that workspace and holds the required permission.

**Frontend shows empty states**
Static pages render only validated generated data. Run
`python scripts/generate_web_data.py` to rebuild `web/public/data/*.json`.

## FAQ

**Does ToolTrace send telemetry?** No. Nothing leaves your machine by default.

**Can I benchmark real LLM providers?** Yes — adapters are optional extras;
configure credentials via environment/keychain resolution. Secrets never persist
into traces.

**Is this a leaderboard?** Public pages rank only within compatible cohorts
(same protocol/task/scorer versions). There is no single universal score.

**What does "reproducibility score" mean?** It measures metadata completeness
(task/scorer/sandbox/model), not scientific validity.

**How do I contribute a task pack?** `tooltrace task scaffold`, fill in YAML +
fixtures, then `tooltrace lint --path`, `tooltrace dry-run`, `tooltrace task test`.
See CONTRIBUTING.md.