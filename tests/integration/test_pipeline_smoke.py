from src.main import run_agent_session
from src.models.schemas import GateDecision, RunStatus, WorkloadSpec
from src.orchestrator.hitl_gate import ScriptedApprovalChannel

WL = WorkloadSpec(name="legacy", cpu_cores=4, ram_gb=16, disk_gb=100,
                  monthly_requests=500000, is_stateful=False)


def test_full_pipeline_all_approved(capsys):
    approvals = [GateDecision(step_id=i, approved=True) for i in range(2, 7)]  # 5 gates
    status = run_agent_session(channel=ScriptedApprovalChannel(approvals), workload=WL)
    assert status == RunStatus.COMPLETED
    assert "PIPELINE COMPLETE" in capsys.readouterr().out
