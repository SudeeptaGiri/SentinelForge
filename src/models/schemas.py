"""Shared Pydantic data contracts + orchestrator-internal types.

Single source of truth for objects that flow between every agent, the
supervisor, and the HITL gates. Everyone imports from here.

Step-seam contracts: at the run_fn boundary the pipeline expects the types
defined in THIS file. Use CostEstimate (not cost_models.CostComparison) and
AuditReport (not security_models.SecurityAuditReport) as the returned artifact.
Scaffold domain models may be used internally by agents for richer data but
must be converted before being returned to the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_PRE_STEP_CONFIRMATION = "WAITING_PRE_STEP_CONFIRMATION"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class RunStatus(str, Enum):
    """Pipeline-level run status (used by the sync supervisor and state manager)."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class RiskLevel(str, Enum):
    LOW_READ_ONLY_ESTIMATION = "LOW_READ_ONLY_ESTIMATION"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WorkloadSpec(BaseModel):
    name: str
    cpu_cores: float
    ram_gb: float
    disk_gb: float
    monthly_requests: int
    is_stateful: bool


class CostEstimate(BaseModel):
    platform: str  # "GCE" | "GKE" | "CloudRun"
    monthly_cost_usd: float
    breakdown: dict[str, float]


class MigrationPlan(BaseModel):
    baseline: CostEstimate
    target: CostEstimate
    target_platform: str
    monthly_savings_usd: float
    savings_pct: float
    rationale: str


class CodeDiff(BaseModel):
    branch_name: str
    files_changed: list[str]
    diff_text: str
    unit_tests_added: list[str]


class InfraArtifacts(BaseModel):
    main_tf: str
    service_yaml: str
    cloudbuild_yaml: str
    validation_passed: bool
    validation_findings: list[str]


class AuditReport(BaseModel):
    target_url: str
    vulnerabilities_found: int
    critical_count: int
    findings: list[str]


class GateDecision(BaseModel):
    step_id: int
    approved: bool
    feedback: str | None = None


class GateRequest(BaseModel):
    step_id: int
    gate_name: str
    summary: str
    tools_used: list[str] = Field(default_factory=list)
    artifact: dict = Field(default_factory=dict)


class AnalysisResult(BaseModel):
    """Output of Person 3's analysis_agent — input to the propose step."""

    detected_platform: str
    summary: str
    files_of_interest: list[str] = Field(default_factory=list)


class PreStepConfirmation(BaseModel):
    """Payload shown in the Pre-Step Confirmation Modal (see ui_progress_tracker_and_gates.md)."""

    event_type: str = "PRE_STEP_CONFIRMATION_REQUIRED"
    pipeline_id: str
    step_number: int
    total_steps: int
    step_name: str
    sub_agent: str
    preview_summary: str
    tools_to_invoke: list[str]
    estimated_duration_seconds: int
    risk_level: RiskLevel


class PipelineStepView(BaseModel):
    """Serializable view of one stepper row, sent to the UI over SSE."""

    step_id: int
    name: str
    sub_agent: str
    status: StepStatus
    active_tool: str = ""
    latest_log: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class PipelineStep:
    id: int
    name: str
    gate_name: str | None
    run_fn: Callable[["PipelineContext", str | None], Any]


@dataclass
class PipelineContext:
    workload: WorkloadSpec | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    def store(self, step: "PipelineStep", artifact: Any) -> None:
        self.artifacts[step.name] = artifact

    def get(self, name: str) -> Any:
        return self.artifacts.get(name)
