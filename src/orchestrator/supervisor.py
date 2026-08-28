"""Main ADK Supervisor Agent (routes tasks & manages the demo pipeline).

Description: Primary orchestrator; walks the Migration/Cost-Optimization
             demo scenario (see team_hackathon_plan.md) through its 6
             pipeline steps and 5 HITL gates, delegating to each teammate's
             specialist agent. Steps not yet owned by a teammate fall back to
             clearly-marked mocks so the end-to-end flow always runs.
Need: Without a central router, sub-agents would need to know about each
      other directly, creating tight coupling and unpredictable execution
      order.
Motive: Provide one place that owns the end-to-end control flow described in
        the architecture's Data & Control Flow diagram, pausing at HITL
        gates and streaming live progress to the UI via `progress_tracker`.
"""

from __future__ import annotations

import asyncio

from src.agents.pentest_agent import PentestAgent
from src.models.schemas import (
    CodeDiff,
    CostEstimate,
    MigrationPlan,
    WorkloadSpec,
)
from src.orchestrator.state_manager import PipelineSession
from src.models.schemas import StepStatus

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


class DevSecOpsSupervisor:
    """Routes tasks across specialist sub-agents and enforces HITL gates."""

    def __init__(self, session: PipelineSession) -> None:
        self.session = session
        self.tracker = session.tracker
        self.gate = session.gate
        self.pentest_agent = PentestAgent()

    async def route(self, user_input: str) -> None:
        """Generic entrypoint stub — the hackathon demo uses `run_pipeline`."""
        raise NotImplementedError("Use DevSecOpsSupervisor(session).run_pipeline(workload) for the demo.")

    async def run_pipeline(self, workload: WorkloadSpec) -> dict:
        """Runs the Migration/Cost-Optimization demo scenario end-to-end."""
        try:
            analysis = await self._step_analyze(workload)
            plan = await self._step_propose(workload, analysis)
            approved = await self._request_gate(2, "Approach", f"Recommend migrating '{workload.name}' to {plan.target_platform}: {plan.rationale}")
            if not approved:
                return self._abort("Gate 1 (Approach) rejected")

            diff = await self._step_codegen(plan)
            approved = await self._request_gate(3, "Code Review", f"Branch `{diff.branch_name}` changes {len(diff.files_changed)} file(s): {', '.join(diff.files_changed)}")
            if not approved:
                return self._abort("Gate 2 (Code Review) rejected")

            infra = await self._step_cost_infra(plan)
            approved = await self._request_gate(4, "Cost & Infra", f"${plan.monthly_savings_usd:.2f}/mo savings ({plan.savings_pct:.1f}%). Terraform validated: {infra['validation_passed']}")
            if not approved:
                return self._abort("Gate 3 (Cost & Infra) rejected")

            audit_report = await self._step_test_and_pentest(diff)
            blocked = self.pentest_agent.is_release_blocked(audit_report)
            approved = await self._request_gate(
                5,
                "Security Audit",
                f"{len(audit_report.findings)} finding(s), overall risk {audit_report.overall_risk}."
                + (" RELEASE BLOCKED by CRITICAL finding." if blocked else ""),
            )
            if not approved or blocked:
                return self._abort("Gate 4 (Security Audit) rejected or blocked")

            deployment = await self._step_deploy(infra)
            approved = await self._request_gate(6, "Final Sign-off", f"Ready to deploy to {deployment['url']}")
            if not approved:
                return self._abort("Gate 5 (Final Sign-off) rejected")

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
        self.tracker.update_step_status(1, StepStatus.COMPLETED, log_msg=f"Detected {workload.name} as stateless, no autoscaling.")
        return {"detected_platform": "GCE", "summary": f"{workload.name} is stateless, currently on GCE VM, no autoscaling."}

    async def _step_propose(self, workload: WorkloadSpec, analysis: dict) -> MigrationPlan:
        self.tracker.update_step_status(2, StepStatus.IN_PROGRESS, sub_agent="CostScalingAgent")
        await asyncio.sleep(0.4)  # MOCK: replace with CostScalingAgent.compute_cost_savings() (Person 2)
        baseline = CostEstimate(platform="GCE", monthly_cost_usd=612.0, breakdown={"compute": 480.0, "disk": 132.0})
        target = CostEstimate(platform="CloudRun", monthly_cost_usd=178.0, breakdown={"compute": 150.0, "requests": 28.0})
        savings = baseline.monthly_cost_usd - target.monthly_cost_usd
        plan = MigrationPlan(
            baseline=baseline,
            target=target,
            target_platform="CloudRun",
            monthly_savings_usd=savings,
            savings_pct=round(savings / baseline.monthly_cost_usd * 100, 1),
            rationale="Stateless workload with variable traffic fits serverless scale-to-zero.",
        )
        self.tracker.update_step_status(2, StepStatus.COMPLETED, log_msg="Proposed migration to Cloud Run.")
        return plan

    async def _step_codegen(self, plan: MigrationPlan) -> CodeDiff:
        self.tracker.update_step_status(3, StepStatus.IN_PROGRESS, sub_agent="CodeGeneratorAgent", tool="mcp_server_git.create_branch")
        await asyncio.sleep(0.4)  # MOCK: replace with CodeGeneratorAgent.refactor_module() (Person 4)
        diff = CodeDiff(
            branch_name="feature/cloud-run-migration",
            files_changed=["Dockerfile", "app/healthz.py", "service.yaml"],
            diff_text="+ added /healthz endpoint for Cloud Run readiness probe",
            unit_tests_added=["test_healthz_endpoint"],
        )
        self.tracker.update_step_status(3, StepStatus.COMPLETED, log_msg=f"Committed to {diff.branch_name}.")
        return diff

    async def _step_cost_infra(self, plan: MigrationPlan) -> dict:
        self.tracker.update_step_status(4, StepStatus.IN_PROGRESS, sub_agent="InfraBuilderAgent", tool="templates/terraform/cloud_run.tf.j2")
        await asyncio.sleep(0.4)  # MOCK: replace with InfraBuilderAgent.render_terraform() (Person 2)
        self.tracker.update_step_status(4, StepStatus.COMPLETED, log_msg="Rendered main.tf + cloudbuild.yaml, terraform validate passed.")
        return {"validation_passed": True, "validation_findings": []}

    async def _step_test_and_pentest(self, diff: CodeDiff):
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, sub_agent="QAAgent", tool="pytest")
        await asyncio.sleep(0.3)  # MOCK: replace with QAAgent.self_heal_test_failure() (Person 4)
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, log_msg="Test failed: missing /healthz route. Self-healing...")
        await asyncio.sleep(0.3)
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, log_msg="Patch applied. Re-running tests... all passed.")

        # Real integration point owned by Person 5: security pentest.
        self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, sub_agent="PentestAgent", tool="mcp_server_strix.run_strix_dast_scan")
        report = await asyncio.to_thread(self.pentest_agent.run_security_audit, DEMO_STAGING_URL, "medium")
        self.tracker.update_step_status(5, StepStatus.COMPLETED, log_msg=f"Strix scan: {len(report.findings)} finding(s), risk={report.overall_risk}.")
        return report

    async def _step_deploy(self, infra: dict) -> dict:
        self.tracker.update_step_status(6, StepStatus.IN_PROGRESS, sub_agent="InfraBuilderAgent", tool="mcp_server_cicd.trigger_cloud_build")
        await asyncio.sleep(0.4)  # MOCK: replace with real Cloud Build trigger (Person 2/5, Day 2 stretch)
        deployment = {"url": "https://demo-app.staging.run.app", "status": "DEPLOYED"}
        self.tracker.update_step_status(6, StepStatus.COMPLETED, log_msg=f"Deployed to {deployment['url']}.")
        return deployment

    # -- shared helpers -------------------------------------------------------

    async def _request_gate(self, step_id: int, gate_name: str, summary: str) -> bool:
        decision = await self.gate.request_gate_approval(step_id, gate_name, summary)
        return decision.approved

    def _abort(self, reason: str) -> dict:
        self.session.result = {"status": "ABORTED", "reason": reason}
        return self.session.result

