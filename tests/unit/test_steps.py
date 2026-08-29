from src.models.schemas import AuditReport, MigrationPlan, PipelineContext
from src.orchestrator.steps import build_default_steps, proposal_step, security_step


def test_default_steps_shape():
    steps = build_default_steps()
    assert [s.id for s in steps] == [1, 2, 3, 4, 5, 6]
    assert steps[0].gate_name is None                      # analysis ungated
    gated = [s.gate_name for s in steps if s.gate_name]
    assert gated == [
        "Gate 1 - Approach", "Gate 2 - Code Review", "Gate 3 - Cost & Infra",
        "Gate 4 - Security Audit", "Gate 5 - Final Sign-off",
    ]


def test_analysis_step_returns_detected_architecture():
    from src.models.schemas import WorkloadSpec
    from src.orchestrator.steps import analysis_step
    wl = WorkloadSpec(name="legacy-api", repo_path="fixtures/sample_legacy_app")
    res = analysis_step(PipelineContext(workload=wl), None)
    assert isinstance(res, dict)
    assert res["detected_platform"] == "GCE"
    assert "summary" in res
    assert "endpoints" in res
    assert len(res["endpoints"]) >= 2


def test_analysis_step_with_feedback():
    from src.orchestrator.steps import analysis_step
    res = analysis_step(PipelineContext(workload=None), "Inspect sqlite db lock")
    assert isinstance(res, dict)
    assert "Feedback: Inspect sqlite db lock" in res["summary"]


def test_proposal_step_returns_migration_plan_with_savings():
    plan = proposal_step(PipelineContext(workload=None), None)
    assert isinstance(plan, MigrationPlan)
    assert plan.savings_pct > 0


def test_proposal_step_incorporates_feedback():
    ctx = PipelineContext(workload=None)
    ctx.artifacts["analysis"] = {"detected_platform": "GCE"}
    plan = proposal_step(ctx, "Use Redis instead of Memcached")
    assert isinstance(plan, MigrationPlan)
    assert "Use Redis instead of Memcached" in plan.rationale


def test_security_step_returns_audit_report():
    report = security_step(PipelineContext(workload=None), None)
    assert isinstance(report, AuditReport)
    assert report.critical_count == 0
