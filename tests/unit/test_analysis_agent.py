"""Unit tests for AnalysisAgent in src/agents/analysis_agent.py."""

import pytest
from src.agents.analysis_agent import AnalysisAgent
from src.models.schemas import AnalysisResult, WorkloadSpec

FIXTURE_PATH = "fixtures/sample_legacy_app"


def test_analysis_agent_initialization():
    agent = AnalysisAgent()
    assert agent.adk_agent is not None
    assert agent.adk_agent.name == "analysis_agent"
    assert len(agent.adk_agent.tools) == 5
    tool_names = [getattr(t, "__name__", str(t)) for t in agent.adk_agent.tools]
    assert "analyze_repository" in tool_names
    assert "index_repository" in tool_names
    assert "get_architecture_summary" in tool_names


def test_analysis_agent_analyze_codebase():
    agent = AnalysisAgent()
    result = agent.analyze_codebase(FIXTURE_PATH)

    assert isinstance(result, AnalysisResult)
    assert result.detected_platform == "GCE"
    assert result.framework == "Flask"
    assert result.has_dockerfile is True
    assert result.has_autoscaling is False
    assert result.workload_spec.cpu_cores == 4.0
    assert result.workload_spec.ram_gb == 16.0
    assert result.workload_spec.disk_gb == 50.0
    assert result.workload_spec.monthly_requests == 500000
    assert result.workload_spec.is_stateful is False
    assert len(result.recommendations) >= 2
    assert "Stateless" in result.architecture_type


def test_analysis_agent_impact_analysis():
    agent = AnalysisAgent()
    impact = agent.analyze_impact("query_orders")
    assert impact["target"] == "query_orders"
    assert "callers" in impact
    assert "dependencies" in impact
