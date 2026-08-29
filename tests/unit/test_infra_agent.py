"""Unit tests for InfraBuilderAgent in src/agents/infra_agent.py."""

import pytest
from pathlib import Path
from src.agents.infra_agent import InfraBuilderAgent


def test_infra_builder_agent_initialization():
    """Verify agent can be initialized properly."""
    agent = InfraBuilderAgent()
    assert agent is not None


def test_render_terraform_cloud_run():
    """Verify Terraform HCL is successfully rendered from Cloud Run jinja2 template."""
    agent = InfraBuilderAgent()
    spec = {
        "service_name": "payment-api",
        "target_platform": "cloud_run",
        "region": "us-east1",
        "cpu": "2",
        "memory": "1Gi",
        "image_uri": "gcr.io/my-gcp-project/payment-api:latest",
    }
    tf_hcl = agent.render_terraform(spec)
    
    assert "google_cloud_run_v2_service" in tf_hcl
    assert "payment-api" in tf_hcl
    assert "us-east1" in tf_hcl
    assert "gcr.io/my-gcp-project/payment-api:latest" in tf_hcl
    assert "cpu    = \"2\"" in tf_hcl
    assert "memory = \"1Gi\"" in tf_hcl


def test_render_terraform_gke_autopilot():
    """Verify Terraform HCL is successfully rendered from GKE Autopilot jinja2 template."""
    agent = InfraBuilderAgent()
    spec = {
        "service_name": "ledger-cluster",
        "target_platform": "gke_autopilot",
        "region": "europe-west3",
    }
    tf_hcl = agent.render_terraform(spec)
    
    assert "google_container_cluster" in tf_hcl
    assert "ledger-cluster" in tf_hcl
    assert "europe-west3" in tf_hcl
    assert "enable_autopilot = true" in tf_hcl


def test_render_terraform_default_matching():
    """Confirm the builder falls back cleanly to Cloud Run on unknown platform spec."""
    agent = InfraBuilderAgent()
    spec = {
        "service_name": "fallback-app",
        "target_platform": "unknown_platform",
        "region": "us-central1",
    }
    tf_hcl = agent.render_terraform(spec)
    assert "google_cloud_run_v2_service" in tf_hcl


def test_render_cicd_pipeline():
    """Verify GCP cloudbuild.yaml step pipeline is generated successfully."""
    agent = InfraBuilderAgent()
    spec = {
        "service_name": "my-worker",
        "region": "us-central1",
        "image_uri": "gcr.io/my-proj/my-worker:latest",
    }
    yaml = agent.render_cicd_pipeline(spec)
    assert "gcr.io/cloud-builders/docker" in yaml
    assert "run" in yaml
    assert "deploy" in yaml
    assert "my-worker" in yaml


def test_security_policy_violations_blocked():
    """Assert that public bindings or wildcards raise ValueError exceptions."""
    agent = InfraBuilderAgent()
    
    # Check that a public binding error triggers a failure
    with pytest.raises(ValueError, match="restricted pattern 'allUsers'"):
        agent._scan_hcl_for_violations("member = \"allUsers\"", "test-service")

    # Check that open external CIDRs trigger a failure
    with pytest.raises(ValueError, match="restricted pattern '0.0.0.0/0'"):
        agent._scan_hcl_for_violations("cidr_blocks = [\"0.0.0.0/0\"]", "test-service")


def test_infra_agent_adk_wrapping():
    """Verify ADK agent config and tool bindings."""
    agent = InfraBuilderAgent()
    assert agent.adk_agent.name == "infra_builder_agent"
    assert "generate_terraform_tool" in [t.__name__ for t in agent.adk_agent.tools]
    assert "generate_cicd_pipeline_tool" in [t.__name__ for t in agent.adk_agent.tools]


def test_infra_agent_adk_tools_execution():
    """Directly execute ADK tools in isolation."""
    from src.agents.infra_agent import generate_terraform_tool, generate_cicd_pipeline_tool
    
    hcl = generate_terraform_tool("payment-rest")
    assert "google_cloud_run_v2_service" in hcl
    assert "payment-rest" in hcl

    yaml = generate_cicd_pipeline_tool("payment-rest")
    assert "gcr.io/cloud-builders/docker" in yaml

