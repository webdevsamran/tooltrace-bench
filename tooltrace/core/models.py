"""Typed public data models for ToolTrace Bench.

These models are the stable public API surface (see README "SDK + Exports").
They are pydantic models so they serialize/deserialize cleanly to JSON for
traces, bundles and reports.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from tooltrace.core.versions import (
    FRAMEWORK_VERSION,
    RESULT_SCHEMA_VERSION,
    TASK_PROTOCOL_VERSION,
    TRACE_SCHEMA_VERSION,
)


class NetworkPolicy(StrEnum):
    """Network access policy for a task."""

    disabled = "disabled"
    allowlisted = "allowlisted"


class Difficulty(StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"
    expert = "expert"


class TrustState(StrEnum):
    """Evidence-backed trust levels for results. Never implied without evidence."""

    LOCAL = "LOCAL"  # produced locally, unverified
    COMMUNITY_VALIDATED = "COMMUNITY_VALIDATED"  # reproduced by a community member
    REPRODUCED = "REPRODUCED"  # reproduced via `tooltrace reproduce`
    MAINTAINER_VERIFIED = "MAINTAINER_VERIFIED"  # verified by a maintainer


class FailureReason(StrEnum):
    """Machine-readable failure taxonomy (12 categories)."""

    none = "none"
    planning = "planning"
    tool_selection = "tool_selection"
    bad_arguments = "bad_arguments"
    execution = "execution"
    environment = "environment"
    verification = "verification"
    hallucinated_resource = "hallucinated_resource"
    timeout = "timeout"
    loop = "loop"
    context_loss = "context_loss"
    destructive_edit = "destructive_edit"
    policy_violation = "policy_violation"


# ---------------------------------------------------------------------------
# Task definition
# ---------------------------------------------------------------------------


class Assertion(BaseModel):
    """A single deterministic assertion evaluated against the final workspace."""

    type: str  # registered scorer name, e.g. "file_exists", "tests_pass"
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float = Field(default=1.0, gt=0)
    description: str = ""


class PerturbationSpec(BaseModel):
    """A controlled fault injected during a run (deterministic, non-offensive)."""

    kind: Literal[
        "tool_failure",
        "command_exit",
        "moved_file",
        "api_error",
        "delay",
        "ambiguous_error",
        "irrelevant_files",
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    apply_at_step: int | None = None  # None = first matching opportunity


class ResourceLimits(BaseModel):
    max_memory_mb: int | None = None
    max_cpus: float | None = None
    max_disk_mb: int | None = None


class TaskDefinition(BaseModel):
    """A versioned benchmark task (validated against schemas/task.schema.json)."""

    schema_version: int = TASK_PROTOCOL_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
    version: str = "1.0.0"
    category: str
    objective: str
    description: str = ""
    starting_workspace: dict[str, str] = Field(default_factory=dict)  # path -> content
    fixtures: dict[str, str] = Field(default_factory=dict)  # read-only reference files
    allowed_tools: list[str]
    assertions: list[Assertion] = Field(min_length=1)
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_steps: int = Field(default=25, ge=1)
    network_policy: NetworkPolicy = NetworkPolicy.disabled
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    difficulty: Difficulty = Difficulty.medium
    tags: list[str] = Field(default_factory=list)
    perturbations: list[PerturbationSpec] = Field(default_factory=list)
    long_context: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def pack(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.id.split("/", 1)[1]


# ---------------------------------------------------------------------------
# Tool events
# ---------------------------------------------------------------------------


class ToolEvent(BaseModel):
    """Sanitized record of one tool invocation. Never contains secrets."""

    timestamp: str
    seq: int
    tool: str
    args_summary: str
    duration_ms: float
    status: Literal["ok", "error", "denied"]
    result_summary: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

TraceEventType = Literal[
    "task_start",
    "agent_message",
    "tool_request",
    "tool_result",
    "workspace_diff",
    "validation",
    "retry_recovery",
    "task_end",
]


class TraceEvent(BaseModel):
    """One event in the versioned JSONL trace."""

    schema_version: int = TRACE_SCHEMA_VERSION
    timestamp: str
    seq: int
    type: TraceEventType
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Usage / telemetry
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class UsageMetadata(BaseModel):
    """Usage data. Token counts only when the adapter provides them; cost only
    when a provider explicitly reports it — never estimated or invented."""

    tokens: TokenUsage | None = None
    model_time_ms: float | None = None
    provider_cost_reported: float | None = None
    currency: str | None = None


# ---------------------------------------------------------------------------
# Scoring / results
# ---------------------------------------------------------------------------


class Score(BaseModel):
    total: float = Field(ge=0.0, le=1.0)
    components: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)


class EvalResult(BaseModel):
    """Outcome of evaluating one agent on one task."""

    schema_version: int = RESULT_SCHEMA_VERSION
    framework_version: str = FRAMEWORK_VERSION
    run_id: str
    task_id: str
    task_version: str
    task_protocol_version: int = TASK_PROTOCOL_VERSION
    agent: str
    agent_config: dict[str, Any] = Field(default_factory=dict)
    success: bool
    partial_success: bool = False
    score: Score
    failure_reason: FailureReason = FailureReason.none
    failure_detail: str = ""
    steps: int = 0
    tool_calls: int = 0
    failed_tool_calls: int = 0
    invalid_tool_calls: int = 0
    repeated_calls: int = 0
    unnecessary_changes: int = 0
    workspace_violations: int = 0
    test_pass_ratio: float | None = None
    wall_ms: float = 0.0
    model_ms: float | None = None
    tool_ms: float = 0.0
    usage: UsageMetadata = Field(default_factory=UsageMetadata)
    trust_state: TrustState = TrustState.LOCAL
    judge_config: dict[str, Any] | None = None  # optional model judge, kept separate
    started_at: str = ""
    finished_at: str = ""
    bundle_path: str | None = None


# ---------------------------------------------------------------------------
# Benchmark runs / comparison
# ---------------------------------------------------------------------------


class BenchmarkRun(BaseModel):
    """Aggregated outcome of one benchmark invocation (possibly N runs/task)."""

    run_id: str
    created_at: str
    config: dict[str, Any] = Field(default_factory=dict)
    compatibility_key: str
    results: list[EvalResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class MetricComparison(BaseModel):
    metric: str
    baseline: float | None
    current: float | None
    delta: float | None
    direction: Literal["higher_is_better", "lower_is_better"]
    threshold: float | None = None
    passed: bool = True


class RegressionReport(BaseModel):
    baseline_id: str
    current_id: str
    compatibility_key: str
    comparisons: list[MetricComparison] = Field(default_factory=list)
    passed: bool = True
    exit_code: int = 0


# ---------------------------------------------------------------------------
# Agent-facing types
# ---------------------------------------------------------------------------


class AgentAction(BaseModel):
    """An action an agent wants to take; interpreted by the runner."""

    kind: Literal["tool", "finish", "message"] = "message"
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    usage_delta: UsageMetadata | None = None


class AgentContext(BaseModel):
    """What an agent sees when initialized for a task."""

    task_id: str
    objective: str
    description: str
    workspace_files: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    max_steps: int = 25
    timeout_seconds: float = 120.0
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentOutcome(BaseModel):
    """Final output of an agent run."""

    messages: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)  # path -> content
    final_output: str = ""
    finish_reason: Literal["finished", "max_steps", "timeout", "error", "aborted"] = "finished"
    usage: UsageMetadata = Field(default_factory=UsageMetadata)
