"""Task protocol v2: explicit domain, difficulty, deterministic seed,
capability requirements, allowed side effects, scoring contract, HITL states,
dual-control user actions, multi-agent roles, checkpoints and migration from v1.

v1 tasks remain fully loadable via :func:`migrate_v1_to_v2`; old readers keep
working because v1 models are untouched.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from tooltrace.core.models import Assertion, Difficulty, NetworkPolicy, ResourceLimits


class Domain(StrEnum):
    coding = "coding"
    os = "os"
    database = "database"
    api = "api"
    web = "web"
    knowledge = "knowledge"
    spreadsheet = "spreadsheet"
    git = "git"
    devops = "devops"
    security = "security"
    multimodal = "multimodal"
    voice = "voice"
    desktop = "desktop"
    mobile = "mobile"
    workflow = "workflow"


class SideEffect(StrEnum):
    """Side effects a task explicitly permits. Anything not listed here that
    the agent attempts is a policy violation (scored by metrics.policy)."""

    filesystem_write = "filesystem_write"
    network_local = "network_local"
    network_external = "network_external"
    process_spawn = "process_spawn"
    package_install = "package_install"
    service_restart = "service_restart"
    db_write = "db_write"
    git_history_change = "git_history_change"


class CapabilityRequirement(BaseModel):
    name: str
    min_version: str | None = None


class ScoringContract(BaseModel):
    """How this task is scored. ``judge_required`` must be False whenever all
    assertions are executable; judge dependency is reported separately."""

    primary_metric: str = "score_total"
    weights_declared: bool = True
    judge_required: bool = False
    partial_credit: bool = False
    description: str = ""


ContaminationLevel = Literal["none", "low", "medium", "high"]


class ContaminationRisk(BaseModel):
    """Honest, non-provable contamination flagging (see PRODUCT_GAPS #1)."""

    level: ContaminationLevel = "none"
    rationale: str = ""
    assessed_at: str = ""
    assessor: str = ""


NetworkProfile = Literal["offline", "local-fixtures-only", "allowlist"]


class Prerequisites(BaseModel):
    required_binaries: list[str] = Field(default_factory=list)
    min_disk_mb: int = 0
    network_profile: NetworkProfile = "offline"


class HumanStep(BaseModel):
    """A modeled human approval/input gate (HITL). Deterministic harnesses
    answer these from ``expected_input``; real deployments can route them."""

    id: str
    prompt: str
    expected_input: str = ""
    blocks_until_answered: bool = True


class UserAction(BaseModel):
    """Dual-control: a scripted simulated-user action mutating world state."""

    at_step: int = Field(ge=0)
    kind: Literal["write_file", "delete_file", "append_file", "message"]
    path: str = ""
    content: str = ""
    message: str = ""


class AgentRole(BaseModel):
    role: Literal["planner", "worker", "reviewer"]
    channel: str = "default"


class CheckpointStage(BaseModel):
    """Long-horizon stage with its own partial-credit assertions."""

    id: str
    after_step_hint: int | None = None
    assertions: list[Assertion] = Field(default_factory=list)


class Attachment(BaseModel):
    """Multimodal attachment referenced by deterministic hash, never embedded."""

    path: str
    media_type: str  # e.g. image/png, audio/wav
    sha256: str = ""


class TaskDefinitionV2(BaseModel):
    protocol_version: int = Field(default=2, frozen=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
    version: str = "2.0.0"
    domain: Domain
    difficulty: Difficulty = Difficulty.medium
    seed: int | None = None  # deterministic seed when the task involves randomness
    objective: str
    description: str = ""
    starting_workspace: dict[str, str] = Field(default_factory=dict)
    fixtures: dict[str, str] = Field(default_factory=dict)
    attachments: list[Attachment] = Field(default_factory=list)
    allowed_tools: list[str]
    capability_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    allowed_side_effects: list[SideEffect] = Field(
        default_factory=lambda: [SideEffect.filesystem_write]
    )
    scoring_contract: ScoringContract = Field(default_factory=ScoringContract)
    assertions: list[Assertion] = Field(min_length=1)
    checkpoints: list[CheckpointStage] = Field(default_factory=list)
    human_steps: list[HumanStep] = Field(default_factory=list)
    user_actions: list[UserAction] = Field(default_factory=list)  # dual-control
    roles: list[AgentRole] = Field(default_factory=list)  # multi-agent
    long_horizon: bool = False
    adversarial_notes: str = ""  # safe robustness notes (misleading names etc.)
    network_policy: NetworkPolicy = NetworkPolicy.disabled
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    prerequisites: Prerequisites = Field(default_factory=Prerequisites)
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_steps: int = Field(default=25, ge=1)
    budgets: dict[str, float] = Field(default_factory=dict)  # e.g. max_tokens, max_cost_usd
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def pack(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.id.split("/", 1)[1]

    def is_dual_control(self) -> bool:
        return len(self.user_actions) > 0

    def is_hitl(self) -> bool:
        return len(self.human_steps) > 0

    def is_multi_agent(self) -> bool:
        return len(self.roles) > 1


_V1_DOMAIN_MAP = {
    "fileops": Domain.coding,
    "bugfix": Domain.coding,
    "testrepair": Domain.coding,
    "refactor": Domain.coding,
    "docsfix": Domain.knowledge,
    "datatransform": Domain.spreadsheet,
    "dataanalysis": Domain.spreadsheet,
    "gitwork": Domain.git,
    "shellwork": Domain.os,
    "mockapi": Domain.api,
    "planning": Domain.workflow,
    "recovery": Domain.workflow,
}


def migrate_v1_to_v2(v1: Any) -> TaskDefinitionV2:
    """Migrate a v1 TaskDefinition to v2 without losing information.

    Mapping rules (documented in docs/MIGRATION.md):
    - category -> domain via an explicit map, fallback 'workflow'
    - perturbations preserved under metadata.v1_perturbations (engine unchanged)
    - long_context maps to long_horizon; everything else carries over directly.
    """
    category = str(getattr(v1, "category", "workflow"))
    domain = _V1_DOMAIN_MAP.get(category, Domain.workflow)
    side_effects = [SideEffect.filesystem_write]
    if getattr(v1, "network_policy", NetworkPolicy.disabled) != NetworkPolicy.disabled:
        side_effects.append(SideEffect.network_local)
    if any(t in ("shell", "git") for t in getattr(v1, "allowed_tools", [])):
        side_effects.append(SideEffect.process_spawn)
    perturbs = [p.model_dump(mode="json") for p in getattr(v1, "perturbations", [])]
    return TaskDefinitionV2(
        id=str(v1.id),
        version="2.0.0",
        domain=domain,
        difficulty=getattr(v1, "difficulty", Difficulty.medium),
        objective=str(v1.objective),
        description=str(getattr(v1, "description", "")),
        starting_workspace=dict(getattr(v1, "starting_workspace", {}) or {}),
        fixtures=dict(getattr(v1, "fixtures", {}) or {}),
        allowed_tools=list(getattr(v1, "allowed_tools", []) or []),
        allowed_side_effects=side_effects,
        assertions=list(getattr(v1, "assertions", []) or []),
        long_horizon=bool(getattr(v1, "long_context", False)),
        network_policy=getattr(v1, "network_policy", NetworkPolicy.disabled),
        resource_limits=getattr(v1, "resource_limits", ResourceLimits()),
        timeout_seconds=float(getattr(v1, "timeout_seconds", 120.0)),
        max_steps=int(getattr(v1, "max_steps", 25)),
        tags=list(getattr(v1, "tags", []) or []),
        metadata={
            **dict(getattr(v1, "metadata", {}) or {}),
            "migrated_from_protocol": 1,
            "v1_perturbations": perturbs,
        },
    )
