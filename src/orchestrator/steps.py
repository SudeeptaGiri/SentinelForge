"""Day-1 stub run_fns for the six pipeline steps + the default step list.

Each run_fn has signature (ctx: PipelineContext, feedback: str | None) -> artifact.
Teammates replace individual stubs with real agents; the signature is the seam.
"""

from __future__ import annotations

from src.models.schemas import (
    AuditReport, CodeDiff, CostEstimate, InfraArtifacts, MigrationPlan,
    PipelineContext, PipelineStep,
)


def analysis_step(ctx: PipelineContext, feedback: str | None) -> dict:
    return {"summary": "Stateless Flask API on a GCE VM, no autoscaling",
            "detected_platform": "GCE"}


def proposal_step(ctx: PipelineContext, feedback: str | None) -> MigrationPlan:
    baseline = CostEstimate(platform="GCE", monthly_cost_usd=120.0,
                            breakdown={"vcpu": 90.0, "ram": 30.0})
    target = CostEstimate(platform="CloudRun", monthly_cost_usd=48.0,
                          breakdown={"vcpu": 30.0, "ram": 18.0})
    savings = baseline.monthly_cost_usd - target.monthly_cost_usd
    return MigrationPlan(
        baseline=baseline, target=target, target_platform="CloudRun",
        monthly_savings_usd=savings,
        savings_pct=round(savings / baseline.monthly_cost_usd * 100, 1),
        rationale="Stateless + bursty traffic fits serverless Cloud Run.",
    )


def codegen_step(ctx: PipelineContext, feedback: str | None) -> CodeDiff:
    return CodeDiff(
        branch_name="migrate/cloud-run",
        files_changed=["app/main.py", "Dockerfile"],
        diff_text="+ @app.get('/healthz')\n+ def healthz():\n+     return {'ok': True}",
        unit_tests_added=["tests/test_healthz.py"],
    )


def infra_step(ctx: PipelineContext, feedback: str | None) -> InfraArtifacts:
    return InfraArtifacts(
        main_tf='resource "google_cloud_run_v2_service" "app" { name = "app" }',
        service_yaml="apiVersion: serving.knative.dev/v1\nkind: Service",
        cloudbuild_yaml="steps:\n  - name: gcr.io/cloud-builders/docker",
        validation_passed=True, validation_findings=[],
    )


def security_step(ctx: PipelineContext, feedback: str | None) -> AuditReport:
    return AuditReport(
        target_url="https://demo-app.staging.run.app",
        vulnerabilities_found=2, critical_count=0,
        findings=["low: missing security header", "low: verbose error page"],
    )


def deploy_step(ctx: PipelineContext, feedback: str | None) -> dict:
    return {"status": "deployed", "url": "https://demo-app.staging.run.app"}


def build_default_steps() -> list[PipelineStep]:
    return [
        PipelineStep(1, "analysis", None, analysis_step),
        PipelineStep(2, "proposal", "Gate 1 - Approach", proposal_step),
        PipelineStep(3, "codegen", "Gate 2 - Code Review", codegen_step),
        PipelineStep(4, "infra", "Gate 3 - Cost & Infra", infra_step),
        PipelineStep(5, "test_pentest", "Gate 4 - Security Audit", security_step),
        PipelineStep(6, "deploy", "Gate 5 - Final Sign-off", deploy_step),
    ]
