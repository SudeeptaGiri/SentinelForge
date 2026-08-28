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

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.web.routes import router as web_router

app = FastAPI(title="SentinelForge DevSecOps Agent")
app.include_router(web_router)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "web" / "static")),
    name="static",
)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


def run_agent_session() -> None:
    """Entrypoint that starts a supervised agent session (see orchestrator/supervisor.py)."""
    raise NotImplementedError


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)

