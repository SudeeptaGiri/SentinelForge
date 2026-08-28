"""Main supervisor: routes intent and runs the gated pipeline loop.

Description: Owns the end-to-end control flow. Iterates a declarative list of
             PipelineSteps; after each gated step it asks Gemini for a summary,
             presents the HITL gate, and on reject re-runs the step with the
             human's feedback (bounded by max_retries).
"""

from __future__ import annotations

import logging

from src.models.schemas import (
    GateRequest, PipelineContext, PipelineStep, RunStatus, WorkloadSpec,
)
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import HITLGateController
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.steps import build_default_steps

logger = logging.getLogger(__name__)

MAX_RETRIES = 3  # mirrors config/agent_config.yaml -> agents.supervisor.max_retries


class DevSecOpsSupervisor:
    """Routes tasks and enforces HITL gates across the pipeline."""

    def __init__(
        self,
        gate: HITLGateController,
        state: SessionStateManager,
        gemini: GeminiClient | None = None,
        steps: list[PipelineStep] | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.gate = gate
        self.state = state
        self.gemini = gemini or GeminiClient()
        self.steps = steps if steps is not None else build_default_steps()
        self.max_retries = max_retries

    def route(self, user_input: str, pipeline_id: str = "demo",
              workload: WorkloadSpec | None = None) -> RunStatus:
        scenario = self.gemini.classify_intent(user_input)
        logger.info("Routed intent %r -> scenario %r", user_input, scenario)
        return self.run_pipeline(pipeline_id, workload or self._demo_workload())

    def run_pipeline(self, pipeline_id: str, workload: WorkloadSpec) -> RunStatus:
        self.state.create_run(pipeline_id)
        ctx = PipelineContext(workload=workload)

        for step in self.steps:
            self.state.set_current(pipeline_id, step.id)
            feedback: str | None = None

            for attempt in range(self.max_retries + 1):
                self.state.set_status(pipeline_id, RunStatus.RUNNING)
                try:
                    artifact = step.run_fn(ctx, feedback)
                except Exception as exc:  # noqa: BLE001 - record and bound-retry
                    self.state.record_error(pipeline_id, step.id, str(exc))
                    if attempt == self.max_retries:
                        self.state.set_status(pipeline_id, RunStatus.FAILED)
                        return RunStatus.FAILED
                    feedback = f"previous attempt raised: {exc}"
                    continue

                ctx.store(step, artifact)
                if step.gate_name is None:
                    break

                payload = self._as_dict(artifact)
                summary = self.gemini.summarize_for_gate(step.name, payload)
                self.state.set_status(pipeline_id, RunStatus.WAITING_APPROVAL)
                request = GateRequest(step_id=step.id, gate_name=step.gate_name,
                                      summary=summary, tools_used=[step.name],
                                      artifact=payload)
                decision = self.gate.request_gate_approval(pipeline_id, request)
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == self.max_retries:
                    self.state.set_status(pipeline_id, RunStatus.REJECTED)
                    return RunStatus.REJECTED

        self.state.set_status(pipeline_id, RunStatus.COMPLETED)
        print("PIPELINE COMPLETE")
        return RunStatus.COMPLETED

    @staticmethod
    def _as_dict(artifact) -> dict:
        if hasattr(artifact, "model_dump"):
            return artifact.model_dump()
        if isinstance(artifact, dict):
            return artifact
        return {"value": str(artifact)}

    @staticmethod
    def _demo_workload() -> WorkloadSpec:
        return WorkloadSpec(name="legacy-api", cpu_cores=4, ram_gb=16, disk_gb=100,
                            monthly_requests=500_000, is_stateful=False)
