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
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.models.schemas import WorkloadSpec
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import PIPELINE_STEPS, AsyncDevSecOpsSupervisor

router = APIRouter()
state_manager = SessionStateManager()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_DIST_DIR = Path(__file__).resolve().parent / "dist"
_DIST_INDEX = _DIST_DIR / "index.html"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class PipelineStartRequest(BaseModel):
    repo_path: str = "fixtures/sample_legacy_app"
    app_name: str = "legacy-app"
    intent: str = "migrate_cloud"  # new_feature | from_scratch | migrate_cloud | migrate_modern


class GateDecisionRequest(BaseModel):
    approved: bool
    feedback: str | None = None
    edited_files: dict[str, str] | None = None


@router.get("/")
async def index(request: Request):
    if _DIST_INDEX.exists():
        return FileResponse(str(_DIST_INDEX))
    return templates.TemplateResponse(request, "index.html", {"steps": PIPELINE_STEPS})


@router.post("/api/pipeline/start")
async def start_pipeline(body: PipelineStartRequest) -> dict:
    workload = WorkloadSpec(
        name=body.app_name,
        repo_path=body.repo_path,
    )
    session = state_manager.create_session(PIPELINE_STEPS)
    session.intent    = body.intent
    session.app_name  = body.app_name
    session.repo_path = body.repo_path
    supervisor = AsyncDevSecOpsSupervisor(session)

    async def _run() -> None:
        try:
            await supervisor.run_pipeline(workload)
        except Exception as exc:  # noqa: BLE001
            session.error = str(exc)

    asyncio.create_task(_run())
    return {"pipeline_id": session.pipeline_id}


@router.get("/api/pipelines")
async def list_pipelines() -> list[dict]:
    """Returns metadata for all in-memory sessions (for history panel)."""
    sessions = state_manager._sessions
    return [
        {
            "pipeline_id": s.pipeline_id,
            "app_name":    s.app_name,
            "repo_path":   s.repo_path,
            "intent":      s.intent,
            "result":      s.result,
            "error":       s.error,
        }
        for s in sessions.values()
    ]


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


@router.get("/api/pipeline/{pipeline_id}/analysis")
async def pipeline_analysis(pipeline_id: str) -> dict:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    return {
        "analysis": session.analysis_data,
        "spec": session.spec_data,
        "plan": session.plan_data,
        "codegen": session.codegen_data,
        "graph": {
            "nodes": session.graph_nodes or [],
            "edges": session.graph_edges or [],
        },
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
    resolved = session.gate.submit_decision(step_id, decision.approved, decision.feedback, decision.edited_files)
    if not resolved:
        raise HTTPException(status_code=409, detail="No pending gate awaiting a decision for this step")
    return {"resolved": True}


@router.get("/api/pipeline/{pipeline_id}/audit")
async def gate_audit_log(pipeline_id: str) -> list[dict]:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    return session.gate.get_audit_log()
