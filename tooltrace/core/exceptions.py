"""Exception hierarchy for ToolTrace Bench.

All exceptions derive from :class:`ToolTraceError` so callers can catch the
whole family. CLI commands translate these into actionable error messages and
stable exit codes.
"""

from __future__ import annotations


class ToolTraceError(Exception):
    """Base class for all ToolTrace Bench errors."""

    exit_code = 1


class TaskValidationError(ToolTraceError):
    """A task definition failed schema or semantic validation."""

    exit_code = 2


class SandboxError(ToolTraceError):
    """Sandbox creation, enforcement or cleanup failed."""

    exit_code = 3


class PolicyViolation(ToolTraceError):
    """An agent action violated task policy (tool allowlist, boundary, network)."""

    exit_code = 4


class AgentError(ToolTraceError):
    """An agent adapter failed to initialize or run."""

    exit_code = 5


class BundleError(ToolTraceError):
    """A result bundle is missing, corrupt or fails checksum verification."""

    exit_code = 6


class ComparisonError(ToolTraceError):
    """Two runs cannot be compared (incompatible versions/protocols)."""

    exit_code = 7


class RegressionThresholdError(ToolTraceError):
    """A regression check failed its configured thresholds."""

    exit_code = 8


class SecretScanError(ToolTraceError):
    """Likely secrets were detected in content destined for publication."""

    exit_code = 9
