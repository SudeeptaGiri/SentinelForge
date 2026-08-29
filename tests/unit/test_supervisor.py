from src.models.schemas import GateDecision, PipelineContext, PipelineStep, RunStatus, WorkloadSpec
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import HITLGateController, ScriptedApprovalChannel
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import DevSecOpsSupervisor

WL = WorkloadSpec(name="x", cpu_cores=4, ram_gb=16, disk_gb=100,
                  monthly_requests=500000, is_stateful=False)


def _supervisor(decisions, steps, max_retries=3):
    state = SessionStateManager()
    gate = HITLGateController(ScriptedApprovalChannel(decisions), state)
    sup = DevSecOpsSupervisor(gate=gate, state=state, gemini=GeminiClient(api_key=None),
                              steps=steps, max_retries=max_retries)
    return sup, state


def test_all_approved_completes(capsys):
    steps = [
        PipelineStep(1, "a", None, lambda c, f: {"ok": 1}),
        PipelineStep(2, "b", "Gate 1 - Approach", lambda c, f: {"ok": 2}),
    ]
    sup, state = _supervisor([GateDecision(step_id=2, approved=True)], steps)
    result = sup.run_pipeline("p1", WL)
    assert result == RunStatus.COMPLETED
    assert state.get("p1").status == RunStatus.COMPLETED
    assert "PIPELINE COMPLETE" in capsys.readouterr().out


def test_reject_reruns_step_with_feedback():
    seen: list[str | None] = []

    def gated(ctx, feedback):
        seen.append(feedback)
        return {"attempt": len(seen)}

    steps = [PipelineStep(2, "b", "Gate 1 - Approach", gated)]
    sup, state = _supervisor(
        [GateDecision(step_id=2, approved=False, feedback="add healthz"),
         GateDecision(step_id=2, approved=True)],
        steps,
    )
    result = sup.run_pipeline("p1", WL)
    assert result == RunStatus.COMPLETED
    assert seen == [None, "add healthz"]   # feedback fed back on the re-run


def test_reject_past_budget_rejects():
    steps = [PipelineStep(2, "b", "Gate 1 - Approach", lambda c, f: {"x": 1})]
    sup, state = _supervisor(
        [GateDecision(step_id=2, approved=False, feedback="no"),
         GateDecision(step_id=2, approved=False, feedback="still no")],
        steps, max_retries=1,
    )
    assert sup.run_pipeline("p1", WL) == RunStatus.REJECTED
    assert state.get("p1").status == RunStatus.REJECTED


def test_step_exception_fails_after_budget():
    def boom(ctx, feedback):
        raise ValueError("kaboom")

    steps = [PipelineStep(1, "a", None, boom)]
    sup, state = _supervisor([], steps, max_retries=1)
    assert sup.run_pipeline("p1", WL) == RunStatus.FAILED
    assert any(e["event"] == "error" for e in state.get("p1").history)


def test_route_classifies_then_runs(capsys):
    from src.orchestrator.steps import build_default_steps
    approvals = [GateDecision(step_id=i, approved=True) for i in range(2, 7)]
    state = SessionStateManager()
    gate = HITLGateController(ScriptedApprovalChannel(approvals), state)
    sup = DevSecOpsSupervisor(gate=gate, state=state, gemini=GeminiClient(api_key=None),
                              steps=build_default_steps())
    assert sup.route("cut my cloud bill", pipeline_id="p1", workload=WL) == RunStatus.COMPLETED
