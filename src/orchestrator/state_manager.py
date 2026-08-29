"""In-memory session state, gate checkpoints, and run history.

Description: Tracks each pipeline run's status, current step, gate decisions,
             and an event history. Two session models coexist:
             - RunState / SessionStateManager (sync): used by the terminal demo
               and all unit tests; compatible with the sync HITLGateController.
             - PipelineSession / create_session (async): used by the web UI
               path; creates AsyncHITLGateController + ProgressTrackerEngine.
             In-memory for the hackathon demo; swap save_checkpoint/
             load_checkpoint for Vertex AI Agent Engine persistence without
             changing any caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.models.checkpoints import GateCheckpoint
from src.models.schemas import GateDecision, RunStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Sync path (terminal demo + unit tests)
# ---------------------------------------------------------------------------

@dataclass
class RunState:
    pipeline_id: str
    status: RunStatus = RunStatus.PENDING
    current_step_id: int | None = None
    history: list[dict] = field(default_factory=list)
    gate_checkpoints: list[GateCheckpoint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Async path (web UI — Person 5)
# ---------------------------------------------------------------------------

@dataclass
class PipelineSession:
    pipeline_id: str
    tracker: Any  # ProgressTrackerEngine (imported lazily to avoid circular deps)
    gate: Any     # AsyncHITLGateController
    history: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    analysis_data: dict[str, Any] | None = None   # populated after step 1
    graph_nodes: list[dict] | None = None          # vis.js node list for UI graph
    graph_edges: list[dict] | None = None          # vis.js edge list for UI graph
    intent: str = "migrate_cloud"
    spec_data: dict[str, Any] | None = None        # populated after step 2 (SpecAgent)
    plan_data: dict[str, Any] | None = None        # populated after step 2 (MigrationPlan)
    codegen_data: dict[str, Any] | None = None     # populated after step 3 (CodeDiff, editable)
    app_name: str = ""
    repo_path: str = ""


class SessionStateManager:
    """Persists and retrieves agent session state and checkpoints."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._sessions: dict[str, PipelineSession] = {}
        self._checkpoints: dict[str, dict] = {}

    # --- sync run API (used by HITLGateController + DevSecOpsSupervisor) ---

    def create_run(self, pipeline_id: str) -> RunState:
        run = RunState(pipeline_id=pipeline_id)
        self._runs[pipeline_id] = run
        self._event(run, "run_created")
        return run

    def get(self, pipeline_id: str) -> RunState:
        return self._runs[pipeline_id]

    def set_current(self, pipeline_id: str, step_id: int) -> None:
        run = self._runs[pipeline_id]
        run.current_step_id = step_id
        self._event(run, "step_started", step_id=step_id)

    def set_status(self, pipeline_id: str, status: RunStatus) -> None:
        run = self._runs[pipeline_id]
        run.status = status
        self._event(run, "status_changed", status=status.value)

    def record_gate(self, pipeline_id: str, decision: GateDecision, gate_name: str) -> None:
        run = self._runs[pipeline_id]
        run.gate_checkpoints.append(
            GateCheckpoint(
                gate_name=gate_name,
                session_id=pipeline_id,
                payload={"step_id": decision.step_id, "feedback": decision.feedback},
                approved=decision.approved,
            )
        )
        self._event(run, "gate_decision", gate=gate_name,
                    approved=decision.approved, feedback=decision.feedback)

    def record_error(self, pipeline_id: str, step_id: int, error: str) -> None:
        run = self._runs[pipeline_id]
        self._event(run, "error", step_id=step_id, error=error)

    def to_dict(self, pipeline_id: str) -> dict:
        run = self._runs[pipeline_id]
        return {
            "pipeline_id": run.pipeline_id,
            "status": run.status.value,
            "current_step_id": run.current_step_id,
            "history": run.history,
            "gate_checkpoints": [c.model_dump() for c in run.gate_checkpoints],
        }

    def _event(self, run: RunState, event: str, **fields) -> None:
        run.history.append({"ts": _now(), "event": event, **fields})

    # --- async session API (used by AsyncDevSecOpsSupervisor + web routes) ---

    def create_session(self, steps: list[str]) -> PipelineSession:
        from src.orchestrator.hitl_gate import AsyncHITLGateController
        from src.orchestrator.progress_tracker import ProgressTrackerEngine

        pipeline_id = f"pipe-devsecops-{uuid.uuid4().hex[:8]}"
        tracker = ProgressTrackerEngine(pipeline_id, steps)
        gate = AsyncHITLGateController(tracker=tracker)
        session = PipelineSession(pipeline_id=pipeline_id, tracker=tracker, gate=gate)
        self._sessions[pipeline_id] = session
        return session

    def get_session(self, pipeline_id: str) -> PipelineSession | None:
        return self._sessions.get(pipeline_id)

    # --- scaffold-compatible checkpoint API ---

    def save_checkpoint(self, session_id: str, payload: dict) -> None:
        self._checkpoints[session_id] = payload

    def load_checkpoint(self, session_id: str) -> dict:
        return self._checkpoints.get(session_id, {})
