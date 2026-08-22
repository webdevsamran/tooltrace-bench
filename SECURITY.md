# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x   | ✅        |

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Report privately via GitHub Security Advisories ("Report a vulnerability" on the
Security tab) or contact the lead maintainer at
**webdevsamran@users.noreply.github.com**.

Include: affected version/commit, reproduction steps, impact assessment, and any
logs (sanitized — never include secrets).

You will receive an acknowledgment within 7 days and a status update within 30
days. We credit reporters in release notes unless they prefer anonymity.

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
  [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for honest boundaries.
- All tool events are sanitized before persistence; known secret patterns
  (API keys, bearer tokens, credentials) are redacted.
- Publication checks fail on likely secrets before anything is exported.
- CI uses least-privilege permissions, pinned Action SHAs, and no secrets.