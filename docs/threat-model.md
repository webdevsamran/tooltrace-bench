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

These limits are not asserted from reading the code — they are **attempted on
every CI run**. `scripts/sandbox_escape_check.py` runs sixteen escapes through
`ToolExecutor` (traversal and absolute paths across every filesystem tool,
network egress under a disabled policy, the cloud metadata endpoint, remote
git operations) and fails the build if any of them succeeds. The two limits
above are attempted too, and reported as confirmed rather than skipped: a
suite that quietly omits the attacks it would fail measures nothing. If one of
them ever starts being blocked, the script says so, so this section can be
tightened rather than left overstating what an attacker can do.

## Docker sandbox (`DockerSandbox`, optional extra)

Everything in this section is **exercised by `scripts/docker_sandbox_check.py`
in CI**, not asserted. That distinction matters more here than anywhere else on
this page: the Docker provider makes the strongest claims, so it is the one
people actually rely on, and an untested strong claim is worse than a tested
weak one.

**Provides, and verified:**

| Claim | How it is checked |
| --- | --- |
| The agent sees only the mounted workspace | The container reads a seeded file, writes one back to the host workspace, and `ls /` is inspected for host paths |
| No outbound network (`--network none`) | A real outbound connection to `1.1.1.1:53` is attempted and must fail. Confirmed non-vacuous: the same check passes the connection when the provider is switched to `--network bridge` |
| Declared `resource_limits` are applied | The container reads its own `/sys/fs/cgroup/memory.max` and it must match the task's declared limit. A task asking for 64 MB gets 64 MiB, not the previously hardcoded 512 MB |
| Timeouts terminate the container | A `sleep 30` under a 5s timeout must return exit 124 rather than hanging |
| Cleanup removes the workspace | The directory must not exist after `cleanup()` |

Limits come from the task's `resource_limits`, falling back to 512 MB / 1.0
CPU. `--memory-swap` is pinned equal to `--memory`, because a container
allowed to swap past its memory limit is not bounded in any way that matters,
and `--pids-limit 256` bounds fork bombs.

**Does NOT provide:**

- Protection against container-runtime vulnerabilities or kernel escapes. The
  boundary is as strong as the host's Docker installation, no stronger.
- Protection when the container is run with a weaker network policy. The
  default is `none`; passing something else is your decision and voids the
  network claim above.
- Disk quota enforcement. `ResourceLimits.max_disk_mb` is accepted by the task
  schema but **is not enforced by this provider** — it would need a sized
  volume or a filesystem quota, neither of which is wired up. Do not read a
  declared `max_disk_mb` as a guarantee.
- Secrets management beyond what you configure; do not mount your home
  directory into benchmark containers.
- Any isolation on Windows or macOS runners. The conformance suite runs on
  `ubuntu-latest` only, so on other platforms these guarantees are inferred
  from Docker's own behaviour rather than verified here.

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