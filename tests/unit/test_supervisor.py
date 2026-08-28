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


import asyncio as _asyncio

def _run_async(coro):
    return _asyncio.run(coro)


def _make_async_session():
    from src.orchestrator.state_manager import SessionStateManager
    from src.orchestrator.supervisor import PIPELINE_STEPS
    sm = SessionStateManager()
    session = sm.create_session(PIPELINE_STEPS)
    return session


def test_async_supervisor_retries_on_rejection():
    """Rejected gate triggers step re-run with feedback; second attempt approved."""
    session = _make_async_session()
    feedback_seen = []

    async def _scenario():
        from src.orchestrator.supervisor import AsyncDevSecOpsSupervisor
        sup = AsyncDevSecOpsSupervisor(session)

        # Patch _step_propose to record feedback
        original_propose = sup._step_propose
        async def patched_propose(workload, analysis, feedback=None):
            feedback_seen.append(feedback)
            return await original_propose(workload, analysis, feedback=feedback)
        sup._step_propose = patched_propose

        # First gate: reject; second gate: approve all remaining
        call_count = [0]
        original_gate = sup._request_gate
        async def patched_gate(step_id, gate_name, summary, artifact=None):
            call_count[0] += 1
            if step_id == 2 and call_count[0] == 1:
                from src.models.schemas import GateDecision
                return GateDecision(step_id=step_id, approved=False, feedback="use GKE instead")
            from src.models.schemas import GateDecision
            return GateDecision(step_id=step_id, approved=True)
        sup._request_gate = patched_gate

        return await sup.run_pipeline(
            __import__('src.models.schemas', fromlist=['WorkloadSpec']).WorkloadSpec(
                name="test-app", cpu_cores=4, ram_gb=16,
                disk_gb=100, monthly_requests=500_000, is_stateful=False
            )
        )

    result = _run_async(_scenario())
    assert result["status"] == "DEPLOYED"
    # First propose call has None feedback; second has the rejection feedback
    assert None in feedback_seen
    assert "use GKE instead" in feedback_seen


def test_async_supervisor_aborts_after_max_retries():
    """After MAX_RETRIES+1 rejections on the same step, pipeline is ABORTED."""
    session = _make_async_session()

    async def _scenario():
        from src.orchestrator.supervisor import AsyncDevSecOpsSupervisor
        sup = AsyncDevSecOpsSupervisor(session)

        async def always_reject(step_id, gate_name, summary, artifact=None):
            from src.models.schemas import GateDecision
            return GateDecision(step_id=step_id, approved=False, feedback="never good enough")
        sup._request_gate = always_reject

        from src.models.schemas import WorkloadSpec
        return await sup.run_pipeline(
            WorkloadSpec(name="x", cpu_cores=2, ram_gb=8,
                         disk_gb=50, monthly_requests=100_000, is_stateful=False)
        )

    result = _run_async(_scenario())
    assert result["status"] == "ABORTED"
    assert "max retries" in result["reason"].lower()
