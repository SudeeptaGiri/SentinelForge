"""Human-in-the-Loop Confirmation Gate Controller.

Description: Enforces the interactive confirmation gates (Approach, Code
             Review, Cost & Infra, Security Audit, Final Production
             Sign-off) and blocks pipeline progression until a human
             responds — either via the terminal (Day-1 fallback) or via the
             web UI's Approve/Reject buttons (`src/web/routes.py`).
Need: A fully autonomous pipeline that generates code, provisions infra, and
      deploys to production is too risky without mandatory human checkpoints,
      and those checkpoints must work identically whether the human answers
      from a terminal prompt or clicks a button in the browser.
Motive: Guarantee that no irreversible or costly action (code merge, cloud
        spend, production deploy) happens without explicit human sign-off,
        matching the gates defined in the architecture's control flow, while
        giving the UI (Person 5) a single async API to drive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from src.models.schemas import GateDecision, StepStatus
from src.orchestrator.progress_tracker import ProgressTrackerEngine

logger = logging.getLogger("sentinelforge.gate")

# Default max wait before a gate auto-rejects (prevents zombie pipelines).
DEFAULT_GATE_TIMEOUT_SECONDS = 3600  # 1 hour


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


class HITLGateController:
    """Blocks pipeline progression until a human approves the current gate."""

    def __init__(
        self,
        tracker: ProgressTrackerEngine | None = None,
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
        """Pauses the pipeline until a decision is submitted for `step_id`.

        Auto-rejects after `timeout_seconds` to prevent zombie pipelines
        that hold cloud resources indefinitely without human response.
        """
        tools_used = tools_used or []
        entry = GateAuditEntry(
            step_id=step_id,
            gate_name=step_name,
            summary=summary,
            tools_used=tools_used,
            requested_at=time.time(),
        )
        self.audit_log.append(entry)

        logger.info("Gate %d (%s) requested: %s", step_id, step_name, summary)

        if self.tracker:
            self.tracker.update_step_status(
                step_id=step_id,
                status=StepStatus.WAITING_APPROVAL,
                log_msg=f"Awaiting human approval for '{step_name}': {summary}",
            )

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[step_id] = future
        try:
            decision = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            decision = GateDecision(step_id=step_id, approved=False, feedback="Auto-rejected: gate timed out without human response")
            logger.warning("Gate %d (%s) auto-rejected after %ds timeout", step_id, step_name, self.timeout_seconds)
        finally:
            self._pending.pop(step_id, None)

        entry.decided_at = time.time()
        entry.approved = decision.approved
        entry.feedback = decision.feedback
        logger.info("Gate %d (%s) %s (%.1fs wait)", step_id, step_name, "APPROVED" if decision.approved else "REJECTED", entry.wait_seconds)

        if self.tracker:
            status = StepStatus.COMPLETED if decision.approved else StepStatus.REJECTED
            log = "Approved by reviewer." if decision.approved else f"Rejected: {decision.feedback or 'no reason given'}"
            self.tracker.update_step_status(step_id=step_id, status=status, log_msg=log)
        return decision

    def submit_decision(self, step_id: int, approved: bool, feedback: str | None = None) -> bool:
        """Called by the web UI (or any client) to resolve a pending gate."""
        future = self._pending.get(step_id)
        if future is None or future.done():
            return False
        future.set_result(GateDecision(step_id=step_id, approved=approved, feedback=feedback))
        return True

    def get_audit_log(self) -> list[dict]:
        """Returns the full gate audit trail for compliance reporting."""
        return [
            {
                "step_id": e.step_id,
                "gate_name": e.gate_name,
                "summary": e.summary,
                "tools_used": e.tools_used,
                "approved": e.approved,
                "feedback": e.feedback,
                "wait_seconds": e.wait_seconds,
            }
            for e in self.audit_log
        ]

    def resolve_from_cli(self, step_id: int, step_name: str, summary: str) -> GateDecision:
        """Synchronous terminal fallback: `input("Approve? [y/n]: ")`."""
        print(f"\n--- GATE {step_id}: {step_name} ---\n{summary}")
        answer = input("Approve? [y/n]: ").strip().lower()
        return GateDecision(step_id=step_id, approved=answer in ("y", "yes", ""))
