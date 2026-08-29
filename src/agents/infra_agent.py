"""Terraform HCL & Kubernetes/Cloud Run Manifest Generator.

Description: Generates production-ready Terraform HCL (`main.tf`) and
             Cloud Run/GKE YAML manifests using pre-built Jinja2 templates,
             scans outputs for security rule violations (CIS-aligned), and
             optionally enriches them using Gemini AI.
Need: Manually writing IaC for every generated app is slow and error-prone;
      it also needs to stay consistent with the cost/scaling decisions made
      upstream.
Motive: Turn the approved cost/scaling plan directly into deployable,
        version-controlled infrastructure code, ready for Gate 3 review.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from google.adk.agents import Agent

from src.utils.template_engine import render_template
from src.utils.genai_client import build_genai_client

logger = logging.getLogger(__name__)


class InfraBuilderAgent:
    """Renders Terraform HCL and CI/CD manifests from approved templates."""

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name
        self._client, self._auth_mode, _ = build_genai_client()
        self._init_adk_agent()

    def _init_adk_agent(self) -> None:
        self.adk_agent = Agent(
            name="infra_builder_agent",
            description="Generates production-ready Terraform HCL and Cloud Build pipeline manifests.",
            model=self.model_name,
            instruction=(
                "You are the SentinelForge Infrastructure-as-Code (IaC) Architect Agent. "
                "You generate structurally correct, compliant Terraform HCL using pre-built Jinja2 templates "
                "and Cloud Build YAML pipelines. You scan generated code for CIS/NIST security violations.\n\n"
                "CRITICAL RULES:\n"
                "1. If requested to generate Terraform HCL or Main.tf, invoke `generate_terraform_tool(...)` directly.\n"
                "2. If requested to generate Cloud Build YAML config, invoke `generate_cicd_pipeline_tool(...)` directly.\n"
                "3. Enforce maximum safety: never output public bindings (allUsers) or unrestricted CIDRs (0.0.0.0/0)."
            ),
            tools=[generate_terraform_tool, generate_cicd_pipeline_tool],
        )

    def render_terraform(self, resource_spec: dict) -> str:
        """Renders Terraform HCL using Jinja2 templates based on resource spec,

        and runs security scan checks to prevent insecure configurations.

        Args:
            resource_spec: Dictionary containing service_name, target_platform,
                           region, memory, CPU, and container image_uri.
        """
        platform = resource_spec.get("target_platform", "cloud_run").lower()
        service_name = resource_spec.get("service_name", "my-app")
        region = resource_spec.get("region", "us-central1")
        image_uri = resource_spec.get("image_uri", "gcr.io/your-project-id/my-app:latest")
        cpu = resource_spec.get("cpu", "1")
        memory = resource_spec.get("memory", "512Mi")

        # Map platform to matching jinja2 template
        template_map = {
            "cloudrun": "terraform/cloud_run.tf.j2",
            "cloud_run": "terraform/cloud_run.tf.j2",
            "gke": "terraform/gke_autopilot.tf.j2",
            "gke_autopilot": "terraform/gke_autopilot.tf.j2",
        }

        template_path = template_map.get(platform, "terraform/cloud_run.tf.j2")
        context = {
            "service_name": service_name,
            "cluster_name": service_name,
            "region": region,
            "image_uri": image_uri,
            "cpu": cpu,
            "memory": memory,
        }

        logger.info("Rendering Terraform template %s with service %s", template_path, service_name)
        hcl = render_template(template_path, context)

        # 1. Enrich HCL using Gemini (if client is available)
        if self._client:
            hcl = self._enrich_hcl_with_llm(hcl, resource_spec)

        # 2. Safety scan check: validate against blocked patterns in security_rules.yaml
        self._scan_hcl_for_violations(hcl, service_name)

        return hcl

    def render_cicd_pipeline(self, resource_spec: dict) -> str:
        """Renders gcp cloudbuild.yaml step pipeline for container builds and deployment."""
        service_name = resource_spec.get("service_name", "my-app")
        region = resource_spec.get("region", "us-central1")
        image_uri = resource_spec.get("image_uri", f"gcr.io/your-project-id/{service_name}:latest")

        context = {
            "service_name": service_name,
            "region": region,
            "image_uri": image_uri,
        }
        return render_template("cicd/cloudbuild.yaml.j2", context)

    def _enrich_hcl_with_llm(self, hcl: str, spec: dict) -> str:
        """Use Gemini to enrich the base template (e.g. adding labels, project variables)."""
        prompt = (
            "You are an expert Google Cloud Terraform Architect.\n"
            "Given the following base rendered Terraform HCL and resource requirements, "
            "enrich it by adding proper resource labels (tier: frontend/backend), "
            "default description strings, and parameterized variable declarations for project_id and region.\n\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY the enriched valid Terraform HCL.\n"
            "2. Do not include markdown commentary, code blocks, or triple backticks.\n"
            "3. Do not modify the resource structure or delete GKE Autopilot settings.\n\n"
            f"Base HCL:\n{hcl}\n\n"
            f"Requirements Spec:\n{yaml.dump(spec)}"
        )
        try:
            logger.info("Calling Gemini (%s) to enrich generated HCL with metadata labels...", self.model_name)
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            if response and response.text:
                clean_text = response.text.strip().removeprefix("```hcl").removeprefix("```").removesuffix("```").strip()
                if "resource " in clean_text:
                    return clean_text
        except Exception as e:
            logger.warning("LLM enrichment failed, falling back to base template: %s", e)
        return hcl

    def _scan_hcl_for_violations(self, hcl: str, service_name: str) -> None:
        """Enforces NIST SP 800-53 / CIS aligned security checks against config limits."""
        rules_path = Path(__file__).parents[2] / "config" / "security_rules.yaml"
        if not rules_path.exists():
            return

        with open(rules_path) as f:
            rules = yaml.safe_load(f).get("security", {}).get("iac_policy", {})

        blocked_patterns = rules.get("blocked_iac_patterns", [])
        for pattern in blocked_patterns:
            if re.search(pattern, hcl):
                logger.error("IaC Security Scan Blocked: Match found for restricted pattern '%s'", pattern)
                raise ValueError(
                    f"Security policy violation in generated Terraform for {service_name}: "
                    f"restricted pattern '{pattern}' detected. Deployments must not expose public IAM bindings or 0.0.0.0/0."
                )


# ADK Tool Wrapper functions
_agent_instance = None


def _get_agent() -> InfraBuilderAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = InfraBuilderAgent()
    return _agent_instance


def generate_terraform_tool(
    service_name: str,
    target_platform: str = "cloud_run",
    region: str = "us-central1",
    cpu: str = "1",
    memory: str = "512Mi",
    image_uri: str = "gcr.io/your-project-id/my-app:latest",
) -> str:
    """Generates complete Terraform HCL (main.tf) and checks for security policy violations."""
    agent = _get_agent()
    spec = {
        "service_name": service_name,
        "target_platform": target_platform,
        "region": region,
        "cpu": cpu,
        "memory": memory,
        "image_uri": image_uri,
    }
    try:
        return agent.render_terraform(spec)
    except Exception as e:
        return f"Generation failed: {e}"


def generate_cicd_pipeline_tool(
    service_name: str,
    region: str = "us-central1",
    image_uri: str = "gcr.io/your-project-id/my-app:latest",
) -> str:
    """Generates a Google Cloud Build CI/CD YAML manifest (cloudbuild.yaml)."""
    agent = _get_agent()
    spec = {
        "service_name": service_name,
        "region": region,
        "image_uri": image_uri,
    }
    return agent.render_cicd_pipeline(spec)



