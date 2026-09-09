# Exit codes

`tooltrace-bench` treats its exit codes as a public contract: CI gates and onboarding
scripts branch on them, so an existing code never changes meaning -- new ones
are appended.

Defined in [`tooltrace/core/exceptions.py`](../tooltrace/core/exceptions.py).

| Code | Name | Meaning |
|---|---|---|
| `0` | `(success)` | No exception was raised. |
| `1` | `ToolTraceError` | Base class for all ToolTrace Bench errors. |
| `2` | `TaskValidationError` | A task definition failed schema or semantic validation. |
| `3` | `SandboxError` | Sandbox creation, enforcement or cleanup failed. |
| `4` | `PolicyViolation` | An agent action violated task policy (tool allowlist, boundary, network). |
| `5` | `AgentError` | An agent adapter failed to initialize or run. |
| `6` | `BundleError` | A result bundle is missing, corrupt or fails checksum verification. |
| `7` | `ComparisonError` | Two runs cannot be compared (incompatible versions/protocols). |
| `8` | `RegressionThresholdError` | A regression check failed its configured thresholds. |
| `9` | `SecretScanError` | Likely secrets were detected in content destined for publication. |

## If you use more than one of these tools

These four projects are independent and their exit codes are **not** a shared
vocabulary. Only `0` means the same thing in all of them (success). Every other
code differs, and two collisions are worth knowing before you write a wrapper:

| Code | api-verity-lab | devrepro-doctor | tooltrace-bench | local-ai-hardware-bench |
|---|---|---|---|---|
| 1 | findings detected | **ready, with warnings** | error | validation error |
| 2 | usage error | **machine blocked** | task validation error | usage error |

The dangerous one is `1`. In devrepro-doctor it means *the machine is usable*;
in the other three it means something went wrong. A wrapper that treats any
non-zero status as failure will block on a DevRepro run that reported success.

The second is `2`: an operator mistake in two of them, and devrepro-doctor's
most important verdict -- the machine cannot build this project -- in the third.

These are not being unified. A shared exit-code library would couple four
independent release cycles, and one of these projects deliberately ships with
no dependencies at all. Knowing the difference is cheaper than removing it.
