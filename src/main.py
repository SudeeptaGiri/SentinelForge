"""Service entrypoint (FastAPI / Agent Engine server).

Description: Exposes REST/gRPC endpoints consumed by the Gemini Enterprise UI
             and external webhooks (e.g. Buganizer, GitHub) to start agent runs,
             and serves the local demo web UI (`src/web/`) with the live
             pipeline stepper and HITL approval gates.
Need: The multi-agent system requires a single, well-defined process boundary
      that external clients and Vertex AI Agent Engine can invoke.
Motive: Provide the thin entrypoint that wires HTTP requests to the
        `DevSecOpsSupervisor` orchestrator without embedding business logic here.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env into os.environ before any agent/client code runs

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.models.schemas import RunStatus, WorkloadSpec
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import (
    ApprovalChannel,
    HITLGateController,
    TerminalApprovalChannel,
)
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import DevSecOpsSupervisor
from src.web.routes import router as web_router

_TAGS_METADATA = [
    {
        "name": "Pipeline",
        "description": (
            "Start and monitor autonomous DevSecOps pipeline runs. "
            "Each run is identified by a `pipeline_id` returned from `/api/pipeline/start`."
        ),
    },
    {
        "name": "Gates",
        "description": (
            "Human-in-the-loop (HITL) approval gates. "
            "The pipeline pauses at each gate and waits for an Approve or Reject decision "
            "before proceeding to the next step."
        ),
    },
    {
        "name": "Cost Estimation",
        "description": (
            "Estimate monthly GCP running costs from a plain-English architecture description. "
            "Prices are fetched live from the GCP Cloud Billing Catalog API when `GCP_API_KEY` "
            "is set; hardcoded fallback rates are used otherwise."
        ),
    },
    {
        "name": "Health",
        "description": "Service liveness check.",
    },
]

app = FastAPI(
    title="SentinelForge DevSecOps Agent",
    description=(
        "Autonomous, multi-agent DevSecOps system built on Google Cloud. "
        "Takes a project idea, bug ticket, or existing repository and carries it "
        "end-to-end through analysis, code generation, cost/infra planning, security "
        "auditing, and deployment — with human-in-the-loop (HITL) approval gates at "
        "every critical decision point.\n\n"
        "**Authentication:** Set `GEMINI_API_KEY` and optionally `GCP_API_KEY` (for live "
        "pricing) in your `.env` file before starting the server.\n\n"
        "**Quick start:** `POST /api/pipeline/start` → poll `GET /api/pipeline/{id}/state` "
        "→ approve/reject gates via `POST /api/pipeline/{id}/gate/{step_id}/decision`."
    ),
    version="1.0.0",
    openapi_tags=_TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.include_router(web_router)

dist_assets_dir = Path(__file__).resolve().parent / "web" / "dist" / "assets"
if dist_assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_assets_dir)), name="assets")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "web" / "static")),
    name="static",
)


@app.get("/health", tags=["Health"], summary="Service liveness check")
def health_check() -> dict:
    """Returns `{"status": "ok"}` when the service is running."""
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
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
