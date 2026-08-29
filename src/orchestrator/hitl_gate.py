"""Human-in-the-Loop confirmation gates.

Description: Blocks pipeline progression until a human approves the current
             gate. Two implementations coexist:
             - Sync path (ApprovalChannel ABC + HITLGateController): used by
               the terminal demo and all unit tests.
             - Async path (AsyncHITLGateController): used by the web UI; gates
               are resolved by `POST /runs/{id}/gates/{gate}/decision` from
               `src/web/routes.py`.
Need: A fully autonomous pipeline that generates code, provisions infra, and
      deploys to production is too risky without mandatory human checkpoints.
Motive: Guarantee that no irreversible or costly action happens without
        explicit human sign-off, whether the human answers from a terminal
        prompt or clicks Approve in the browser.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

from src.models.schemas import GateDecision, GateRequest, StepStatus

logger = logging.getLogger("sentinelforge.gate")

DEFAULT_GATE_TIMEOUT_SECONDS = 3600  # 1 hour — prevents zombie pipelines


# ---------------------------------------------------------------------------
# Sync path (terminal demo + unit tests)
# ---------------------------------------------------------------------------

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
    """Day-2 channel (Person 5) — see AsyncHITLGateController for the real impl.

    NOTE (Day-2): Use AsyncHITLGateController instead of this class for the web
    UI path. The ApprovalChannel interface will need `pipeline_id: str` added to
    `request_approval` so the threading.Event can be keyed by run. Terminal and
    Scripted channels can silently accept and ignore it.
    """

    def request_approval(self, request: GateRequest) -> GateDecision:
        raise NotImplementedError("WebApprovalChannel is implemented by Person 5 (Day 2)")


class HITLGateController:
    """Sync gate controller: calls the active ApprovalChannel and records to state.

    Used by the terminal demo (`run_agent_session`) and all unit tests.
    For the web UI path, use AsyncHITLGateController.
    """

    def __init__(self, channel: ApprovalChannel, state) -> None:
        self.channel = channel
        self.state = state

    def request_gate_approval(self, pipeline_id: str, request: GateRequest) -> GateDecision:
        decision = self.channel.request_approval(request)
        self.state.record_gate(pipeline_id, decision, request.gate_name)
        return decision


# ---------------------------------------------------------------------------
# Async path (web UI — Person 5)
# ---------------------------------------------------------------------------

@dataclass
class GateAuditEntry:
    """Immutable record of every gate decision — kept for compliance audit trail."""

    step_id: int
    gate_name: str
    summary: str
    tools_used: list[str]
    requested_at: float
    decided_at: float | None = None
    approved: bool | None = None
    feedback: str | None = None

    @property
    def wait_seconds(self) -> float:
        if self.decided_at is None:
            return 0.0
        return round(self.decided_at - self.requested_at, 2)


class AsyncHITLGateController:
    """Async gate controller for the web UI path.

    Gates block on an asyncio.Future resolved when the user clicks Approve/Reject
    in the browser (`POST /runs/{id}/gates/{gate}/decision` → submit_decision).
    Auto-rejects after timeout_seconds to prevent zombie pipelines.
    """

    def __init__(
        self,
        tracker=None,
        timeout_seconds: int = DEFAULT_GATE_TIMEOUT_SECONDS,
    ) -> None:
        self.tracker = tracker
        self.timeout_seconds = timeout_seconds
        self._pending: dict[int, asyncio.Future] = {}
        self.audit_log: list[GateAuditEntry] = []

    async def request_gate_approval(
        self,
        step_id: int,
        step_name: str,
        summary: str,
        tools_used: list[str] | None = None,
    ) -> GateDecision:
        tools_used = tools_used or []
        entry = GateAuditEntry(
            step_id=step_id, gate_name=step_name, summary=summary,
            tools_used=tools_used, requested_at=time.time(),
        )
        self.audit_log.append(entry)
        logger.info("Gate %d (%s) requested: %s", step_id, step_name, summary)

        if self.tracker:
            self.tracker.update_step_status(
                step_id=step_id, status=StepStatus.WAITING_APPROVAL,
                log_msg=f"Awaiting human approval for '{step_name}': {summary}",
            )

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[step_id] = future
        try:
            decision = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            decision = GateDecision(
                step_id=step_id, approved=False,
                feedback="Auto-rejected: gate timed out without human response",
            )
            logger.warning("Gate %d (%s) auto-rejected after %ds timeout",
                           step_id, step_name, self.timeout_seconds)
        finally:
            self._pending.pop(step_id, None)

        entry.decided_at = time.time()
        entry.approved = decision.approved
        entry.feedback = decision.feedback
        logger.info("Gate %d (%s) %s (%.1fs wait)", step_id, step_name,
                    "APPROVED" if decision.approved else "REJECTED", entry.wait_seconds)

        if self.tracker:
            status = StepStatus.COMPLETED if decision.approved else StepStatus.REJECTED
            log = ("Approved by reviewer." if decision.approved
                   else f"Rejected: {decision.feedback or 'no reason given'}")
            self.tracker.update_step_status(step_id=step_id, status=status, log_msg=log)
        return decision

    def submit_decision(
        self,
        step_id: int,
        approved: bool,
        feedback: str | None = None,
        edited_files: dict[str, str] | None = None,
    ) -> bool:
        """Called by the web UI to resolve a pending gate."""
        future = self._pending.get(step_id)
        if future is None or future.done():
            return False
        future.set_result(GateDecision(step_id=step_id, approved=approved, feedback=feedback,
                                       edited_files=edited_files))
        return True

    def get_audit_log(self) -> list[dict]:
        return [
            {
                "step_id": e.step_id, "gate_name": e.gate_name, "summary": e.summary,
                "tools_used": e.tools_used, "approved": e.approved,
                "feedback": e.feedback, "wait_seconds": e.wait_seconds,
            }
            for e in self.audit_log
        ]
