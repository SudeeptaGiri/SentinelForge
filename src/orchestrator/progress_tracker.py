"""Real-time Progress Tracker & SSE Event Broadcaster for the UI Stepper.

Description: Owns the live state of every step in a pipeline run (status,
             active sub-agent/tool, streaming logs) and fans updates out to
             any number of Server-Sent-Events subscribers (browser tabs).
Need: The Gemini Enterprise / web UI stepper (see
      ui_progress_tracker_and_gates.md) must reflect pipeline state in real
      time without polling, and multiple viewers may watch the same run.
Motive: Centralize "what does the UI currently see" in one place so the
        orchestrator only has to call `update_step_status(...)` and every
        connected client gets the same event stream for free.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from src.models.schemas import PipelineStepView, StepStatus


@dataclass
class PipelineStepState:
    step_id: int
    name: str
    sub_agent: str = ""
    status: StepStatus = StepStatus.PENDING
    active_tool: str = ""
    logs: list[str] = field(default_factory=list)
    started_at: float | None = None

    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return round(time.monotonic() - self.started_at, 1)

    def to_view(self) -> PipelineStepView:
        return PipelineStepView(
            step_id=self.step_id,
            name=self.name,
            sub_agent=self.sub_agent,
            status=self.status,
            active_tool=self.active_tool,
            latest_log=self.logs[-1] if self.logs else "",
            logs=self.logs[-8:],  # keep the UI log list minimal
            elapsed_seconds=self.elapsed_seconds(),
        )


class ProgressTrackerEngine:
    """Tracks step state for one pipeline run and broadcasts SSE updates."""

    def __init__(self, pipeline_id: str, steps: list[str]) -> None:
        self.pipeline_id = pipeline_id
        self.steps: list[PipelineStepState] = [
            PipelineStepState(step_id=i + 1, name=name) for i, name in enumerate(steps)
        ]
        self._subscribers: list[asyncio.Queue] = []

    # -- subscription -----------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        """Registers a new SSE listener (one per open browser connection)."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        # Prime the new subscriber with the full current state.
        queue.put_nowait(self._snapshot_event())
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    # -- state mutation -----------------------------------------------------
    def update_step_status(
        self,
        step_id: int,
        status: StepStatus,
        sub_agent: str = "",
        tool: str = "",
        log_msg: str = "",
    ) -> None:
        step = self.steps[step_id - 1]
        step.status = status
        if status == StepStatus.IN_PROGRESS and step.started_at is None:
            step.started_at = time.monotonic()
        if sub_agent:
            step.sub_agent = sub_agent
        if tool:
            step.active_tool = tool
        if log_msg:
            step.logs.append(log_msg)
        self._broadcast(self._snapshot_event())

    def add_log(self, step_id: int, log_msg: str) -> None:
        """Appends a log line without changing status/sub_agent/tool — for progress pings."""
        step = self.steps[step_id - 1]
        step.logs.append(log_msg)
        self._broadcast(self._snapshot_event())

    def snapshot(self) -> dict:
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        return {
            "pipeline_id": self.pipeline_id,
            "pipeline_progress_pct": round((completed / len(self.steps)) * 100, 1) if self.steps else 0.0,
            "steps": [s.to_view().model_dump() for s in self.steps],
        }

    def _snapshot_event(self) -> str:
        return json.dumps(self.snapshot())

    def _broadcast(self, payload: str) -> None:
        for queue in list(self._subscribers):
            queue.put_nowait(payload)
