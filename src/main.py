"""Service entrypoint (FastAPI / Agent Engine server).

Exposes the health endpoint and wires an agent session to the supervisor.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.models.schemas import RunStatus, WorkloadSpec
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import (
    ApprovalChannel, HITLGateController, TerminalApprovalChannel,
)
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import DevSecOpsSupervisor

app = FastAPI(title="SentinelForge DevSecOps Agent")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


def run_agent_session(
    channel: ApprovalChannel | None = None,
    workload: WorkloadSpec | None = None,
    pipeline_id: str = "demo",
) -> RunStatus:
    """Start a supervised agent session for the migration/cost demo."""
    state = SessionStateManager()
    gate = HITLGateController(channel or TerminalApprovalChannel(), state)
    supervisor = DevSecOpsSupervisor(gate=gate, state=state, gemini=GeminiClient())
    return supervisor.route(
        "Migrate my legacy GCE app to cut monthly cost",
        pipeline_id=pipeline_id,
        workload=workload,
    )


if __name__ == "__main__":
    run_agent_session()
