from src.models.schemas import (
    StepStatus, RunStatus, WorkloadSpec, CostEstimate, MigrationPlan,
    GateDecision, GateRequest, PipelineStep, PipelineContext,
)


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
