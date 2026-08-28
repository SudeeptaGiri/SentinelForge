"""Shared pipeline contracts used across every agent and the orchestrator.

Description: Canonical pydantic schemas (WorkloadSpec, CostEstimate,
             MigrationPlan, CodeDiff, InfraArtifacts, AuditReport,
             GateDecision, PipelineStepState) that flow between every
             teammate's agent code.
Need: Without one shared definition, each agent would invent its own shape
      for the same data, making integration between the 5 workstreams brittle.
Motive: Give every teammate a single import (`from src.models.schemas import
        ...`) so the orchestrator, agents, and UI never disagree on data shape.
"""

from enum import Enum

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_PRE_STEP_CONFIRMATION = "WAITING_PRE_STEP_CONFIRMATION"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


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
