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

## What CodeQL found, and what was behind it

CodeQL (`security-extended`) runs on every push. Seven alerts have been raised
against this project. Four were real, and this section exists partly to record
that the first reading of three of them was wrong.

They were dismissed as false positives on the basis of the flows they *appeared*
to describe. Reading the actual data-flow paths out of the SARIF showed the
analyser was following entirely different routes, and three defects were sitting
at the far end of them:

- **A bearer token gated on a substring.** `scripts/check_action_refs.py`
  attached a GitHub token when `"api.github.com" in url`. That is true of
  `https://elsewhere.example/?next=api.github.com`. Now compares the parsed
  hostname.
- **Six characters of every detected secret, kept for nobody.**
  `SecretFinding.preview` held `text[start:start + 6]`, annotated "never the
  *full* secret" -- a quieter promise than the module's own "never the secret
  itself". Nothing read it. Removed; `start`/`end` already locate the match.
- **A pasted key echoed to stdout.** `tooltrace init` printed
  `api_key_env` in a note, unvalidated. The field named for a variable is the
  one most likely to receive the key itself, and the note reaches stdout and the
  JSON payload. Now refused, dropped from the config, and answered with advice
  to rotate -- without quoting the value back.

A fourth finding came out of the same pass without an alert behind it: the
runtime sanitiser in `tooltrace/security/sanitize.py` had no `stripe-live-key`
or `npm-token` rule, both of which `scripts/secret_scan.py` has. A Stripe live
key in an agent's tool output was written into the user's bundle unredacted,
while the identical string in this repository blocked a release -- their data
protected less carefully than ours. `tests/test_secret_scan_catches_secrets.py`
now checks the two lists for parity on every run.

### The three that remain open

| Alert | Query | Location |
|---|---|---|
| #2, #3 | `py/clear-text-logging-sensitive-data` | `tooltrace/cli/main.py` (`_emit`) |
| #1 | `py/clear-text-storage-sensitive-data` | `tooltrace/security/redaction.py` (`write_record`) |

All three now trace to one source: `redaction_report` builds a list of the
**names** of secret patterns that still match after sanitisation --
`aws-access-key`, not the key -- which flows into the record written to disk and
printed by `tooltrace redaction`. CodeQL's sensitive-data classifier is
name-based, the variable was called `residual_secrets`, and that name is what a
reviewer reads before the expression. It is `residual_classes` now, which is
what it always held.

The property is proven rather than asserted:
[`tests/test_secrets_do_not_leak.py`](tests/test_secrets_do_not_leak.py) plants
an email, a card number and an AWS key in a bundle and checks that none appears
in the report, the record, or either file written to disk.

These are not suppressed in source. A `# codeql[...]` comment on `_emit` would
blanket every command that prints anything, which is exactly the kind of
chokepoint exemption that hides the next real finding -- the same reason the
secret scanner marks single lines instead of exempting `tests/`.