"""Shared Pydantic data contracts + orchestrator-internal types.

Single source of truth for objects that flow between every agent, the
supervisor, and the HITL gates. Everyone imports from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


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
