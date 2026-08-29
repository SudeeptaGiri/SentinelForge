"""Unit tests for shared Pydantic data schemas in src/models/schemas.py."""

import pytest
from src.models.schemas import (
    StepStatus,
    WorkloadSpec,
    AnalysisResult,
    SpecResult,
    CostEstimate,
    MigrationPlan,
    CodeDiff,
    InfraArtifacts,
    AuditReport,
    GateDecision,
)
from src.models.schemas import (
    StepStatus, RunStatus, WorkloadSpec, CostEstimate, MigrationPlan,
    GateDecision, GateRequest, PipelineStep, PipelineContext,
)


def test_workload_spec_defaults():
    spec = WorkloadSpec(name="order-service")
    assert spec.name == "order-service"
    assert spec.cpu_cores == 1.0
    assert spec.ram_gb == 2.0
    assert spec.disk_gb == 10.0
    assert spec.monthly_requests == 100000
    assert spec.is_stateful is False


def test_analysis_result_serialization():
    workload = WorkloadSpec(name="legacy-app", cpu_cores=4.0, ram_gb=16.0, disk_gb=50.0, monthly_requests=500000)
    res = AnalysisResult(
        detected_platform="GCE",
        workload_spec=workload,
        summary="Stateless Flask API on GCE",
        files_of_interest=["app.py", "deploy_gce.sh"],
        framework="Flask",
        has_dockerfile=True,
        has_autoscaling=False,
    )
    json_data = res.model_dump_json()
    assert "GCE" in json_data
    assert "Flask" in json_data

    reconstructed = AnalysisResult.model_validate_json(json_data)
    assert reconstructed.detected_platform == "GCE"
    assert reconstructed.workload_spec.cpu_cores == 4.0


def test_spec_result_serialization():
    spec = SpecResult(
        spec_type="OpenAPI",
        title="Payment Webhook API",
        version="1.0.0",
        summary="Webhook ingest service",
        raw_spec="openapi: 3.1.0\ninfo:\n  title: Test\n  version: 1.0.0\npaths: {}",
        endpoints=[{"path": "/webhooks", "method": "POST"}]
    )
    assert spec.title == "Payment Webhook API"
    assert len(spec.endpoints) == 1
    assert spec.endpoints[0]["method"] == "POST"


def test_pipeline_gate_and_migration_models():
    baseline = CostEstimate(platform="GCE", monthly_cost_usd=140.50, breakdown={"compute": 120.0, "storage": 20.50})
    target = CostEstimate(platform="CloudRun", monthly_cost_usd=12.20, breakdown={"compute": 10.0, "storage": 2.20})
    plan = MigrationPlan(
        baseline=baseline,
        target=target,
        target_platform="CloudRun",
        monthly_savings_usd=128.30,
        savings_pct=91.3,
        rationale="Migrate from idle GCE VM to serverless Cloud Run."
    )
    assert plan.monthly_savings_usd == 128.30
    assert plan.savings_pct == 91.3

    decision = GateDecision(step_id=1, approved=True, feedback="Approved migration plan.")
    assert decision.approved is True


def test_gate_decision_feedback_defaults_none():
    d = GateDecision(step_id=1, approved=True)
    assert d.feedback is None


def test_status_enums_have_expected_members():
    assert StepStatus.WAITING_APPROVAL.value == "WAITING_APPROVAL"
    assert RunStatus.REJECTED.value == "REJECTED"


def test_gate_request_defaults_are_independent():
    a = GateRequest(step_id=1, gate_name="G1", summary="s")
    b = GateRequest(step_id=2, gate_name="G2", summary="s")
    a.tools_used.append("x")
    assert b.tools_used == []  # default_factory, not shared mutable


def test_pipeline_context_store_and_get():
    ctx = PipelineContext(workload=None)
    step = PipelineStep(id=1, name="analysis", gate_name=None, run_fn=lambda c, f: {"ok": True})
    ctx.store(step, {"ok": True})
    assert ctx.get("analysis") == {"ok": True}


def test_migration_plan_roundtrips():
    base = CostEstimate(platform="GCE", monthly_cost_usd=100.0, breakdown={"cpu": 60.0})
    tgt = CostEstimate(platform="CloudRun", monthly_cost_usd=40.0, breakdown={"cpu": 25.0})
    plan = MigrationPlan(baseline=base, target=tgt, target_platform="CloudRun",
                         monthly_savings_usd=60.0, savings_pct=60.0, rationale="stateless")
    assert plan.model_dump()["savings_pct"] == 60.0
