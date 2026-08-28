"""Human-in-the-Loop confirmation gates.

Description: Blocks pipeline progression until a human approves the current
             gate. The approval CHANNEL is pluggable (terminal now, web later);
             the pipeline calls the controller and never changes when the
             channel swaps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from src.models.schemas import GateDecision, GateRequest
from src.orchestrator.state_manager import SessionStateManager


class ApprovalChannel(ABC):
    """Delivers a human approve/reject decision for a gate. Blocking."""

    @abstractmethod
    def request_approval(self, request: GateRequest) -> GateDecision: ...


class TerminalApprovalChannel(ApprovalChannel):
    """Day-1 channel: prints the gate summary and reads a terminal decision."""

    def request_approval(self, request: GateRequest) -> GateDecision:
        print(f"\n=== {request.gate_name} (step {request.step_id}) ===")
        print(request.summary)
        answer = input("Approve? [y/n] or type feedback: ").strip()
        if answer.lower() in ("y", "yes"):
            return GateDecision(step_id=request.step_id, approved=True)
        return GateDecision(step_id=request.step_id, approved=False,
                            feedback=answer or "rejected")


class ScriptedApprovalChannel(ApprovalChannel):
    """Non-interactive channel: returns preset decisions in order.

    Used by tests and headless/demo runs. Raises if asked for more decisions
    than were scripted, to surface mismatched expectations early.
    """

    def __init__(self, decisions: list[GateDecision]) -> None:
        self._queue: deque[GateDecision] = deque(decisions)

    def request_approval(self, request: GateRequest) -> GateDecision:
        if not self._queue:
            raise RuntimeError("ScriptedApprovalChannel exhausted")
        return self._queue.popleft()


class WebApprovalChannel(ApprovalChannel):
    """Day-2 channel (Person 5).

    Design: set run status WAITING_APPROVAL, block on a threading.Event; a
    FastAPI `POST /runs/{id}/gates/{gate}/decision` endpoint sets the decision
    and the event, unblocking the pipeline thread.

    NOTE (Day-2): The ApprovalChannel interface will need to be extended with
    `pipeline_id: str` as a parameter to `request_approval` when implementing
    this channel, so the threading.Event and state.set_status call can be keyed
    by the correct run. TerminalApprovalChannel and ScriptedApprovalChannel
    can silently accept and ignore it.
    """

    def request_approval(self, request: GateRequest) -> GateDecision:
        raise NotImplementedError("WebApprovalChannel is implemented by Person 5 (Day 2)")


class HITLGateController:
    """Calls the active approval channel and records the gate on state."""

    def __init__(self, channel: ApprovalChannel, state: SessionStateManager) -> None:
        self.channel = channel
        self.state = state

    def request_gate_approval(self, pipeline_id: str, request: GateRequest) -> GateDecision:
        decision = self.channel.request_approval(request)
        self.state.record_gate(pipeline_id, decision, request.gate_name)
        return decision
