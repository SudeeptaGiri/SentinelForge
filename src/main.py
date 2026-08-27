"""Service entrypoint (FastAPI / Agent Engine server).

Description: Exposes REST/gRPC endpoints consumed by the Gemini Enterprise UI
             and external webhooks (e.g. Buganizer, GitHub) to start agent runs.
Need: The multi-agent system requires a single, well-defined process boundary
      that external clients and Vertex AI Agent Engine can invoke.
Motive: Provide the thin entrypoint that wires HTTP requests to the
        `DevSecOpsSupervisor` orchestrator without embedding business logic here.
"""

from fastapi import FastAPI

app = FastAPI(title="SentinelForge DevSecOps Agent")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


def run_agent_session() -> None:
    """Entrypoint that starts a supervised agent session (see orchestrator/supervisor.py)."""
    raise NotImplementedError
