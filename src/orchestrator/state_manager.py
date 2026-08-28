"""Session state & conversation history.

Description: Manages in-memory pipeline session state (current step,
             history, tracker/gate handles). A hackathon-appropriate stand-in
             for Vertex AI Agent Engine managed state — swap the storage in
             `save_checkpoint`/`load_checkpoint` for the real Agent Engine
             session API without changing any caller.
Need: Long-running, multi-step agent workflows (spanning analysis, code-gen,
      cost, infra, QA, and security stages) must survive process restarts and
      resume from the last approved checkpoint.
Motive: Provide a single abstraction over session storage so other
        components (orchestrator, web UI) never touch storage APIs directly,
        and so Person 1 can later swap this for real Agent Engine state
        without touching the orchestrator or UI code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from src.orchestrator.hitl_gate import HITLGateController
from src.orchestrator.progress_tracker import ProgressTrackerEngine


@dataclass
class PipelineSession:
    pipeline_id: str
    tracker: ProgressTrackerEngine
    gate: HITLGateController
    history: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


class SessionStateManager:
    """Persists and retrieves agent session state and checkpoints."""

    def __init__(self) -> None:
        self._sessions: dict[str, PipelineSession] = {}
        self._checkpoints: dict[str, dict] = {}

    def create_session(self, steps: list[str]) -> PipelineSession:
        pipeline_id = f"pipe-devsecops-{uuid.uuid4().hex[:8]}"
        tracker = ProgressTrackerEngine(pipeline_id, steps)
        gate = HITLGateController(tracker=tracker)
        session = PipelineSession(pipeline_id=pipeline_id, tracker=tracker, gate=gate)
        self._sessions[pipeline_id] = session
        return session

    def get_session(self, pipeline_id: str) -> PipelineSession | None:
        return self._sessions.get(pipeline_id)

    def save_checkpoint(self, session_id: str, payload: dict) -> None:
        self._checkpoints[session_id] = payload

    def load_checkpoint(self, session_id: str) -> dict:
        return self._checkpoints.get(session_id, {})
