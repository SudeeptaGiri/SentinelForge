"""Main supervisor: routes intent and runs the gated pipeline loop.

Description: Two supervisor implementations coexist:
             - DevSecOpsSupervisor (sync): terminal demo + unit tests. Iterates
               a declarative PipelineStep list; on reject re-runs the step with
               human feedback (bounded by max_retries). All 32 unit tests use
               this class.
             - AsyncDevSecOpsSupervisor (async): web UI path. Walks the same 6
               steps using asyncio, streams progress via ProgressTrackerEngine,
               and uses AsyncHITLGateController for browser-based gate decisions.
"""

from __future__ import annotations

import asyncio
import logging

from src.models.schemas import (
    CodeDiff,
    CostEstimate,
    GateDecision,
    GateRequest,
    MigrationPlan,
    PipelineContext,
    PipelineStep,
    RunStatus,
    StepStatus,
    WorkloadSpec,
)
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import HITLGateController
from src.orchestrator.state_manager import PipelineSession, SessionStateManager
from src.orchestrator.steps import build_default_steps

logger = logging.getLogger(__name__)

MAX_RETRIES = 3  # mirrors config/agent_config.yaml -> agents.supervisor.max_retries

PIPELINE_STEPS = [
    "Codebase Analysis & GraphRAG Indexing",
    "Architecture & Approach Proposal",
    "Application Code Generation & Refactoring",
    "Cost & Infrastructure Optimization",
    "E2E Testing, Self-Healing & Security Pentest",
    "Cloud Build CI/CD & GCP Deployment",
]

# Staging host allowlisted in config/security_rules.yaml (*.staging.internal).
DEMO_STAGING_URL = "https://demo-app.staging.internal"


# ---------------------------------------------------------------------------
# Sync supervisor (terminal demo + unit tests)
# ---------------------------------------------------------------------------

class DevSecOpsSupervisor:
    """Routes tasks and enforces HITL gates across the pipeline (sync path)."""

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


# ---------------------------------------------------------------------------
# Async supervisor (web UI path — Person 5)
# ---------------------------------------------------------------------------

class AsyncDevSecOpsSupervisor:
    """Async supervisor for the web UI path; streams progress to the browser."""

    def __init__(self, session: PipelineSession) -> None:
        from src.agents.pentest_agent import PentestAgent  # lazy: avoids mcp import in sync path
        self.session = session
        self.tracker = session.tracker
        self.gate = session.gate
        self.pentest_agent = PentestAgent()

    async def run_pipeline(self, workload: WorkloadSpec) -> dict:
        """Runs the Migration/Cost-Optimization demo scenario end-to-end."""
        try:
            analysis = await self._step_analyze(workload)

            # ── Step 2 + Gate 1 ──────────────────────────────────────────────
            plan, feedback = None, None
            for attempt in range(MAX_RETRIES + 1):
                plan = await self._step_propose(workload, analysis, feedback=feedback)
                decision = await self._request_gate(
                    2, "Approach",
                    f"Recommend migrating '{workload.name}' to {plan.target_platform}: {plan.rationale}",
                    artifact=plan.model_dump(),
                )
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == MAX_RETRIES:
                    return self._abort(f"Gate 1 (Approach) rejected after {MAX_RETRIES} max retries")
                self.tracker.update_step_status(2, StepStatus.IN_PROGRESS,
                                                log_msg=f"Re-evaluating after rejection: {feedback}")

            # ── Step 3 + Gate 2 ──────────────────────────────────────────────
            diff, feedback = None, None
            for attempt in range(MAX_RETRIES + 1):
                diff = await self._step_codegen(plan, feedback=feedback)
                decision = await self._request_gate(
                    3, "Code Review",
                    f"Branch `{diff.branch_name}` changes {len(diff.files_changed)} file(s): {', '.join(diff.files_changed)}",
                    artifact=diff.model_dump(),
                )
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == MAX_RETRIES:
                    return self._abort(f"Gate 2 (Code Review) rejected after {MAX_RETRIES} max retries")
                self.tracker.update_step_status(3, StepStatus.IN_PROGRESS,
                                                log_msg=f"Re-evaluating after rejection: {feedback}")

            # ── Step 4 + Gate 3 ──────────────────────────────────────────────
            infra, feedback = None, None
            for attempt in range(MAX_RETRIES + 1):
                infra = await self._step_cost_infra(plan, feedback=feedback)
                decision = await self._request_gate(
                    4, "Cost & Infra",
                    f"${plan.monthly_savings_usd:.2f}/mo savings ({plan.savings_pct:.1f}%). "
                    f"Terraform validated: {infra['validation_passed']}",
                    artifact={**infra, "savings_usd": plan.monthly_savings_usd,
                               "savings_pct": plan.savings_pct, "target_platform": plan.target_platform},
                )
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == MAX_RETRIES:
                    return self._abort(f"Gate 3 (Cost & Infra) rejected after {MAX_RETRIES} max retries")
                self.tracker.update_step_status(4, StepStatus.IN_PROGRESS,
                                                log_msg=f"Re-evaluating after rejection: {feedback}")

            # ── Step 5 + Gate 4 ──────────────────────────────────────────────
            audit_report, feedback = None, None
            for attempt in range(MAX_RETRIES + 1):
                audit_report = await self._step_test_and_pentest(diff, feedback=feedback)
                blocked = self.pentest_agent.is_release_blocked(audit_report)
                gate_summary = (
                    f"{len(audit_report.findings)} finding(s), overall risk {audit_report.overall_risk}."
                    + (" RELEASE BLOCKED by CRITICAL finding." if blocked else "")
                )
                decision = await self._request_gate(
                    5, "Security Audit",
                    gate_summary,
                    artifact={
                        "target": audit_report.target,
                        "overall_risk": audit_report.overall_risk,
                        "findings": [{"title": f.title, "severity": f.severity, "cvss": f.cvss_score}
                                     for f in audit_report.findings],
                        "release_blocked": blocked,
                    },
                )
                if blocked:
                    return self._abort("Gate 4 (Security Audit) blocked by CRITICAL finding")
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == MAX_RETRIES:
                    return self._abort(f"Gate 4 (Security Audit) rejected after {MAX_RETRIES} max retries")
                self.tracker.update_step_status(5, StepStatus.IN_PROGRESS,
                                                log_msg=f"Re-evaluating after rejection: {feedback}")

            # ── Step 6 + Gate 5 ──────────────────────────────────────────────
            deployment, feedback = None, None
            for attempt in range(MAX_RETRIES + 1):
                deployment = await self._step_deploy(infra, feedback=feedback)
                decision = await self._request_gate(
                    6, "Final Sign-off",
                    f"Ready to deploy to {deployment['url']}",
                    artifact=deployment,
                )
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == MAX_RETRIES:
                    return self._abort(f"Gate 5 (Final Sign-off) rejected after {MAX_RETRIES} max retries")
                self.tracker.update_step_status(6, StepStatus.IN_PROGRESS,
                                                log_msg=f"Re-evaluating after rejection: {feedback}")

            self.session.result = {
                "status": "DEPLOYED",
                "plan": plan.model_dump(),
                "deployment": deployment,
                "audit": audit_report.model_dump(),
            }
            return self.session.result
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            self.session.error = str(exc)
            raise

    # -- pipeline steps (mocks clearly marked for teammate hand-off) --------

    async def _step_analyze(self, workload: WorkloadSpec) -> dict:
        self.tracker.update_step_status(1, StepStatus.IN_PROGRESS, sub_agent="AnalysisAgent", tool="mcp_graphify_query")
        await asyncio.sleep(0.4)  # MOCK: replace with AnalysisAgent.analyze_impact() (Person 3)
        self.tracker.update_step_status(1, StepStatus.COMPLETED,
                                        log_msg=f"Detected {workload.name} as stateless, no autoscaling.")
        return {"detected_platform": "GCE",
                "summary": f"{workload.name} is stateless, currently on GCE VM, no autoscaling."}

    async def _step_propose(self, workload: WorkloadSpec, analysis: dict, feedback: str | None = None) -> MigrationPlan:
        log_msg = f"Re-evaluating proposal after feedback: {feedback}" if feedback else "Computing migration cost savings..."
        self.tracker.update_step_status(2, StepStatus.IN_PROGRESS, sub_agent="CostScalingAgent",
                                        log_msg=log_msg)
        await asyncio.sleep(0.4)
        baseline = CostEstimate(platform="GCE", monthly_cost_usd=612.0,
                                breakdown={"compute": 480.0, "disk": 132.0})
        target = CostEstimate(platform="CloudRun", monthly_cost_usd=178.0,
                              breakdown={"compute": 150.0, "requests": 28.0})
        savings = baseline.monthly_cost_usd - target.monthly_cost_usd
        rationale = f"Stateless workload with variable traffic fits serverless scale-to-zero."
        if feedback:
            rationale = f"Revised after feedback '{feedback}': {rationale}"
        plan = MigrationPlan(
            baseline=baseline, target=target, target_platform="CloudRun",
            monthly_savings_usd=savings,
            savings_pct=round(savings / baseline.monthly_cost_usd * 100, 1),
            rationale=rationale,
        )
        self.tracker.update_step_status(2, StepStatus.COMPLETED, log_msg="Proposed migration to Cloud Run.")
        return plan

    async def _step_codegen(self, plan: MigrationPlan, feedback: str | None = None) -> CodeDiff:
        log_msg = f"Re-generating code after feedback: {feedback}" if feedback else "Generating migration code..."
        self.tracker.update_step_status(3, StepStatus.IN_PROGRESS, sub_agent="CodeGeneratorAgent",
                                        tool="mcp_server_git.create_branch", log_msg=log_msg)
        await asyncio.sleep(0.4)
        diff = CodeDiff(
            branch_name="feature/cloud-run-migration",
            files_changed=["Dockerfile", "app/healthz.py", "service.yaml"],
            diff_text="+ added /healthz endpoint for Cloud Run readiness probe",
            unit_tests_added=["test_healthz_endpoint"],
        )
        self.tracker.update_step_status(3, StepStatus.COMPLETED, log_msg=f"Committed to {diff.branch_name}.")
        return diff

    async def _step_cost_infra(self, plan: MigrationPlan, feedback: str | None = None) -> dict:
        log_msg = f"Re-generating infra after feedback: {feedback}" if feedback else "Rendering Terraform templates..."
        self.tracker.update_step_status(4, StepStatus.IN_PROGRESS, sub_agent="InfraBuilderAgent",
                                        tool="templates/terraform/cloud_run.tf.j2", log_msg=log_msg)
        await asyncio.sleep(0.4)
        self.tracker.update_step_status(4, StepStatus.COMPLETED,
                                        log_msg="Rendered main.tf + cloudbuild.yaml, terraform validate passed.")
        return {"validation_passed": True, "validation_findings": []}

    async def _step_test_and_pentest(self, diff: CodeDiff, feedback: str | None = None):
        log_msg = f"Re-running security scan after feedback: {feedback}" if feedback else "Running tests..."
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, sub_agent="QAAgent",
                                        tool="pytest", log_msg=log_msg)
        await asyncio.sleep(0.3)
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS,
                                        log_msg="Test failed: missing /healthz route. Self-healing...")
        await asyncio.sleep(0.3)
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS,
                                        log_msg="Patch applied. Re-running tests... all passed.")
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, sub_agent="PentestAgent",
                                        tool="mcp_server_strix.run_strix_dast_scan")
        report = await asyncio.to_thread(self.pentest_agent.run_security_audit, DEMO_STAGING_URL, "medium")
        self.tracker.update_step_status(5, StepStatus.COMPLETED,
                                        log_msg=f"Strix scan: {len(report.findings)} finding(s), risk={report.overall_risk}.")
        return report

    async def _step_deploy(self, infra: dict, feedback: str | None = None) -> dict:
        log_msg = f"Re-attempting deploy after feedback: {feedback}" if feedback else "Triggering Cloud Build..."
        self.tracker.update_step_status(6, StepStatus.IN_PROGRESS, sub_agent="InfraBuilderAgent",
                                        tool="mcp_server_cicd.trigger_cloud_build", log_msg=log_msg)
        await asyncio.sleep(0.4)
        deployment = {"url": "https://demo-app.staging.run.app", "status": "DEPLOYED"}
        self.tracker.update_step_status(6, StepStatus.COMPLETED,
                                        log_msg=f"Deployed to {deployment['url']}.")
        return deployment

    async def _request_gate(
        self,
        step_id: int,
        gate_name: str,
        summary: str,
        artifact: dict | None = None,
    ) -> GateDecision:
        decision = await self.gate.request_gate_approval(
            step_id, gate_name, summary, artifact=artifact
        )
        return decision

    def _abort(self, reason: str) -> dict:
        self.session.result = {"status": "ABORTED", "reason": reason}
        return self.session.result
