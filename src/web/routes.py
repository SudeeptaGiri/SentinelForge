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
from pydantic import BaseModel, Field

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
    repo_path: str = Field(
        default="fixtures/sample_legacy_app",
        description="Path to the repository or legacy app folder to analyse.",
    )
    app_name: str = Field(default="legacy-app", description="Human-readable name for the pipeline run.")
    intent: str = Field(
        default="migrate_cloud",
        description=(
            "Pipeline scenario to execute. "
            "One of: `new_feature`, `from_scratch`, `migrate_cloud`, `migrate_modern`."
        ),
    )


class GateDecisionRequest(BaseModel):
    approved: bool = Field(description="True to approve and advance the pipeline; False to reject.")
    feedback: str | None = Field(default=None, description="Optional free-text feedback shown in the audit log.")
    edited_files: dict[str, str] | None = Field(
        default=None,
        description="Optional map of filename → new content for files the reviewer edited inline.",
    )


class CostEstimateRequest(BaseModel):
    architecture_text: str = Field(
        description=(
            "Plain-English description of the GCP architecture to price. "
            'Example: "3 Cloud Run services (2 vCPU, 1 GB RAM each), '
            '1 Cloud SQL db-n1-standard-2, 500 GB GCS bucket, 5M Pub/Sub messages/month".'
        )
    )
    region: str = Field(default="us-central1", description="GCP region used for pricing lookups.")


@router.get("/", include_in_schema=False)
async def index(request: Request):
    if _DIST_INDEX.exists():
        return FileResponse(str(_DIST_INDEX))
    return templates.TemplateResponse(request, "index.html", {"steps": PIPELINE_STEPS})


@router.post(
    "/api/pipeline/start",
    tags=["Pipeline"],
    summary="Start a pipeline run",
    response_description="The unique pipeline_id for this run.",
)
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


@router.get(
    "/api/pipelines",
    tags=["Pipeline"],
    summary="List all pipeline runs",
    response_description="Metadata for every in-memory pipeline session.",
)
async def list_pipelines() -> list[dict]:
    """Returns id, app name, repo path, intent, result, and error for all sessions."""
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


@router.get(
    "/api/pipeline/{pipeline_id}/state",
    tags=["Pipeline"],
    summary="Get pipeline step state",
    response_description="Current step statuses, active tool, elapsed time, latest result and error.",
)
async def pipeline_state(pipeline_id: str) -> dict:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    return {
        **session.tracker.snapshot(),
        "result": session.result,
        "error": session.error,
    }


@router.get(
    "/api/pipeline/{pipeline_id}/analysis",
    tags=["Pipeline"],
    summary="Get pipeline analysis artifacts",
    response_description="Analysis, spec, plan, codegen output, and knowledge graph nodes/edges.",
)
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


@router.get(
    "/api/pipeline/{pipeline_id}/events",
    tags=["Pipeline"],
    summary="Stream pipeline progress (SSE)",
    response_description="Server-Sent Events stream; each event is a JSON-encoded step update.",
)
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


@router.post(
    "/api/pipeline/{pipeline_id}/gate/{step_id}/decision",
    tags=["Gates"],
    summary="Submit a gate approval or rejection",
    response_description='`{"resolved": true}` on success.',
)
async def submit_gate_decision(pipeline_id: str, step_id: int, decision: GateDecisionRequest) -> dict:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    resolved = session.gate.submit_decision(step_id, decision.approved, decision.feedback, decision.edited_files)
    if not resolved:
        raise HTTPException(status_code=409, detail="No pending gate awaiting a decision for this step")
    return {"resolved": True}


@router.get(
    "/api/pipeline/{pipeline_id}/audit",
    tags=["Gates"],
    summary="Get gate audit log",
    response_description="Chronological list of all gate decisions for compliance review.",
)
async def gate_audit_log(pipeline_id: str) -> list[dict]:
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    return session.gate.get_audit_log()


@router.post(
    "/api/cost/estimate",
    tags=["Cost Estimation"],
    summary="Estimate monthly GCP cost from architecture text",
    response_description=(
        "Per-service line items with unit prices and monthly totals, "
        "plus overall total and pricing disclaimer."
    ),
)
async def cost_estimate(request: CostEstimateRequest) -> dict:
    """
    Parse a plain-English GCP architecture description and return a full monthly cost breakdown.

    **How it works:**
    1. Gemini parses the free-text description into structured service specs (CPU, RAM, storage, requests…).
    2. Live unit prices are fetched from the **GCP Cloud Billing Catalog API** (`cloudbilling.googleapis.com/v1`)
       when `GCP_API_KEY` is configured; hardcoded fallback rates are used otherwise.
    3. Each service is priced independently and returned as a line item.

    **Supported services:** Compute Engine, GKE Autopilot, Cloud Run, Cloud SQL,
    Cloud Storage, BigQuery, Pub/Sub, Load Balancing, Memorystore (Redis), Vertex AI.

    **Example request:**
    ```json
    {
      "architecture_text": "2 Cloud Run services (1 vCPU, 512 MB RAM, 500k req/month), 1 Cloud SQL db-n1-standard-2 with 100 GB storage, 1 GCS bucket with 250 GB",
      "region": "us-central1"
    }
    ```
    """
    from src.mcp_servers.server_cost import estimate_architecture_cost
    try:
        return estimate_architecture_cost(request.architecture_text, request.region)
    except Exception as exc:  # noqa: BLE001 - never let pricing errors crash the UI
        raise HTTPException(status_code=422, detail=f"Cost estimation failed: {exc}")


@router.get(
    "/api/pipeline/{pipeline_id}/gate/{step_id}/detail",
    tags=["Gates"],
    summary="Get gate artifact and summary",
    response_description="The gate's artifact payload and Gemini-generated summary for display.",
)
async def gate_detail(pipeline_id: str, step_id: int) -> dict:
    """Returns the artifact and Gemini summary for a pending or recently resolved gate."""
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    detail = session.gate.get_gate_detail(step_id)
    if not detail:
        raise HTTPException(status_code=404, detail="No gate detail found for this step")
    return detail
