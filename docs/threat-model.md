# Sandbox Threat Model

This document states **honestly** what the ToolTrace Bench sandboxes do and do
not protect against. We never overclaim isolation strength.

## Assets to protect

1. The host filesystem outside the task workspace.
2. Host environment secrets (API keys, tokens, credentials).
3. The network (by default: no outbound access from tasks).
4. Result integrity (traces/bundles must not be tampered with undetectably).

## Local sandbox (`TempWorkspaceSandbox`, default)

**Provides:**

- A fresh temporary directory per run; all tool file operations are resolved
  through a boundary check that rejects absolute paths, `..` traversal, drive
  changes and symlink escapes.
- Network denial at the **tool layer**: the `http` tool refuses every request
  unless the task explicitly allowlists hosts; `git` blocks remote
  subcommands.
- Subprocess execution with wall-clock timeouts and an **allowlisted
  environment** — host secrets not on the allowlist are not passed in.
- Deterministic cleanup of the temporary directory after each run.

**Does NOT provide (known limits):**

- OS-level process isolation. A shell command executed by an agent runs with
  the harness user's privileges and *could* touch files outside the workspace
  via raw syscalls. The boundary check constrains **tool-mediated** access,
  not arbitrary subprocess behavior.
- Kernel-level network blocking. Network policy is enforced by our tools;
  a raw-socket program spawned via `shell` is not blocked by the local
  sandbox.
- Memory/CPU caps (resource-limit fields are recorded but only enforced by
  the Docker provider).

**Consequence:** treat locally-sandboxed agent runs as running code you have
some trust in. For untrusted agents, use the Docker sandbox.

## Docker sandbox (`DockerSandbox`, optional extra)

**Provides (in addition):**

- Container filesystem isolation (`--network none` by default, memory/CPU
  caps) — a much stronger boundary for untrusted agents.

**Does NOT provide:**

- Protection against container-runtime vulnerabilities or kernel escapes.
- Secrets management beyond what you configure; do not mount your home
  directory into benchmark containers.

## Supply chain

- CI runs with least-privilege permissions and pinned Action SHAs.
- No secrets are present in CI; publication checks fail on likely secrets.
- Bundles carry SHA-256 checksums so post-hoc tampering is detectable
  (checksums themselves live inside the bundle manifest — verification of
  provenance requires external anchoring, e.g. git history).

## Non-goals

- Defending against malicious task-pack authors (review required).
- Offensive security testing payloads; perturbations are benign fault
  injection only.