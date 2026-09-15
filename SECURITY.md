# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x   | ✅        |

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Report privately via GitHub Security Advisories ("Report a vulnerability" on the
Security tab) or contact the lead maintainer at
**webdevsamran@users.noreply.github.com**.

Include: affected version/commit, reproduction steps, impact assessment, and any
logs (sanitized — never include secrets).

You will receive an acknowledgment within 7 days and a status update within 30
days. This project has a single maintainer; those are the windows that can
actually be met, rather than a shorter number that sounds better.

We credit reporters in release notes unless they prefer anonymity.

## Scope

In scope:

- Sandbox escape or workspace-boundary violations in `tooltrace.sandbox`
- Secret leakage through traces, events, reports or bundles
- Unsafe subprocess execution in tools
- Supply-chain issues in CI workflows or dependencies

Out of scope:

- Attacks requiring physical access to a contributor's machine
- Social engineering
- Denial-of-service against the GitHub Pages frontend (static hosting)

## Security design notes

- The default sandbox isolates the **workspace filesystem** and disables network
  access at the tool layer. It does **not** claim OS-level isolation; see
  [docs/threat-model.md](docs/threat-model.md) for honest boundaries.
- All tool events are sanitized before persistence; known secret patterns
  (API keys, bearer tokens, credentials) are redacted.
- Publication checks fail on likely secrets before anything is exported.
- CI uses least-privilege permissions, pinned Action SHAs, and no secrets.

## Static-analysis findings that are open on purpose

CodeQL (`security-extended`) runs on every push. Three alerts are open and are
not defects. They are recorded here rather than only in a dismissal box, so the
reasoning is reviewable and can be re-checked when the code changes.

All three come from CodeQL's **name-based** sensitive-data classifier: it treats
identifiers spelled `key`, `secret` or `password` as sensitive sources and then
cannot prove, through a `dict` passed into a function, that the value does not
come back out. The property each alert doubts is instead proven empirically by
[`tests/test_secrets_do_not_leak.py`](tests/test_secrets_do_not_leak.py), which
plants real-shaped secrets and asserts on the actual bytes.

| Alert | Query | Location | Why it fires, and why it is wrong |
|---|---|---|---|
| #4, #5 | `py/clear-text-logging-sensitive-data` | `tooltrace/cli/main.py` (`_emit`) | A verification key reaches `a2a.report()`, whose result is printed. Inside, the key is used only as the first argument to `hmac.new` and `hmac.compare_digest`; the returned structure holds signature *states*, algorithm names and prose. Two tests drive both output paths with a real key and assert it appears in neither stdout nor stderr. |
| #3 | `py/clear-text-storage-sensitive-data` | `tooltrace/security/redaction.py` (`write_record`) | The record contains `residual_secret_classes` -- the **labels** of secret patterns that still match after sanitisation, such as `aws_access_key`, never the matched text. `Finding` documented that in a comment and nothing checked it; a test now plants an email, a card number and an AWS key and asserts none appears in the report, the record, or either file written to disk. |

These are not suppressed in source. A `# codeql[...]` comment on `_emit` would
blanket every command that prints anything, which is exactly the kind of
chokepoint exemption that hides the next real finding -- the same reason the
secret scanner marks single lines instead of exempting `tests/`.