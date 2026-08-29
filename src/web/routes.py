"""FastAPI routes for the DevSecOps Agent demo UI.

Description: Serves the live pipeline stepper page, streams progress over
             Server-Sent Events, accepts pipeline-start requests, and
             resolves HITL gate decisions submitted from Approve/Reject
             buttons in the browser.
Need: The team plan (Person 5) requires replacing the Day-1 terminal
      `input()` approval prompt with a real web UI backed by
      `hitl_gate.HITLGateController`, without changing the orchestrator API.
Motive: Provide the single integration surface between the browser and the
        orchestrator/agents — every teammate's pipeline step becomes visible
        and controllable here once it's implemented.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.models.schemas import WorkloadSpec
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import PIPELINE_STEPS, AsyncDevSecOpsSupervisor

router = APIRouter()
state_manager = SessionStateManager()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Demo workload used for the Migration/Cost-Optimization scenario.
DEMO_WORKLOAD = WorkloadSpec(
    name="legacy-invoice-api",
    cpu_cores=4,
    ram_gb=16,
    disk_gb=100,
    monthly_requests=500_000,
    is_stateful=False,
)


class GateDecisionRequest(BaseModel):
    approved: bool
    feedback: str | None = None


class CostEstimateRequest(BaseModel):
    architecture_text: str
    region: str = "us-central1"


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"steps": PIPELINE_STEPS})


@router.post("/api/pipeline/start")
async def start_pipeline() -> dict:
    session = state_manager.create_session(PIPELINE_STEPS)
    supervisor = AsyncDevSecOpsSupervisor(session)

    async def _run() -> None:
        try:
            await supervisor.run_pipeline(DEMO_WORKLOAD)
        except Exception as exc:  # noqa: BLE001 - logged on the session for the UI to surface
            session.error = str(exc)

    asyncio.create_task(_run())
    return {"pipeline_id": session.pipeline_id}


@router.get("/api/pipeline/{pipeline_id}/state")
async def pipeline_state(pipeline_id: str) -> dict:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    return {
        **session.tracker.snapshot(),
        "result": session.result,
        "error": session.error,
    }


@router.get("/api/pipeline/{pipeline_id}/events")
async def pipeline_events(pipeline_id: str) -> StreamingResponse:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")

    async def _event_stream():
        queue = session.tracker.subscribe()
        try:
            while True:
                payload = await queue.get()
                yield f"data: {payload}\n\n"
        finally:
            session.tracker.unsubscribe(queue)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/api/pipeline/{pipeline_id}/gate/{step_id}/decision")
async def submit_gate_decision(pipeline_id: str, step_id: int, decision: GateDecisionRequest) -> dict:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    resolved = session.gate.submit_decision(step_id, decision.approved, decision.feedback)
    if not resolved:
        raise HTTPException(status_code=409, detail="No pending gate awaiting a decision for this step")
    return {"resolved": True}


@router.get("/api/pipeline/{pipeline_id}/audit")
async def gate_audit_log(pipeline_id: str) -> list[dict]:
    """Returns the compliance audit trail of all gate decisions for this run."""
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    return session.gate.get_audit_log()


@router.post("/api/cost/estimate")
async def cost_estimate(request: CostEstimateRequest) -> dict:
    """Estimate monthly GCP running cost from a plain-text architecture description."""
    from src.mcp_servers.server_cost import estimate_architecture_cost
    try:
        return estimate_architecture_cost(request.architecture_text, request.region)
    except Exception as exc:  # noqa: BLE001 - never let pricing errors crash the UI
        raise HTTPException(status_code=422, detail=f"Cost estimation failed: {exc}")


@router.get("/api/pipeline/{pipeline_id}/gate/{step_id}/detail")
async def gate_detail(pipeline_id: str, step_id: int) -> dict:
    """Returns the artifact and summary for a pending or recently resolved gate."""
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    detail = session.gate.get_gate_detail(step_id)
    if not detail:
        raise HTTPException(status_code=404, detail="No gate detail found for this step")
    return detail
