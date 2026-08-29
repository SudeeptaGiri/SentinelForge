"""Tests for targeted differential CodeGen updates, ReviewAgent, and CodeOptimizer."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.agents.code_gen_agent import CodeGeneratorAgent
from src.agents.review_agent import ReviewAgent, ReviewReport, ReviewIssue
from src.agents.code_optimizer import CodeOptimizerAgent, OptimizationReport
from src.models.schemas import CodeDiff, CostEstimate, MigrationPlan, WorkloadSpec
from src.orchestrator.state_manager import PipelineSession


def test_review_agent_review_code_dict_empty():
    agent = ReviewAgent()
    # When disabled or empty, returns empty report
    report = agent.review_code_dict({})
    assert isinstance(report, ReviewReport)
    assert len(report.all_issues) == 0


def test_review_agent_review_code_dict_with_mocked_client():
    agent = ReviewAgent()
    agent._client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '[]'
    agent._client.models.generate_content.return_value = mock_resp

    files = {
        "src/app.py": "def hello():\n    return 'world'\n",
        "Dockerfile": "FROM python:3.11\nWORKDIR /app\n",
    }
    report = agent.review_code_dict(files, mode="normal")
    assert isinstance(report, ReviewReport)
    assert report.passes_quality_gate()


def test_code_optimizer_optimize_code_dict():
    agent = CodeOptimizerAgent()
    agent._client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "def hello():\n    '''Greet user with type annotation.'''\n    return 'world'\n"
    agent._client.models.generate_content.return_value = mock_resp

    files = {
        "src/app.py": "def hello():\n    return 'world'\n",
        "Dockerfile": "FROM python:3.11\n",
    }
    review_report = {
        "normal_review": {
            "issues": [
                {
                    "severity": "warning",
                    "file_path": "src/app.py",
                    "message": "Missing docstring",
                    "suggestion": "Add docstring to hello",
                }
            ]
        }
    }
    updated_files, opt_report = agent.optimize_code_dict(files, review_report)
    assert isinstance(opt_report, OptimizationReport)
    assert "src/app.py" in updated_files
    assert "Dockerfile" in updated_files


def test_codegen_identify_affected_files_heuristic():
    agent = CodeGeneratorAgent()
    agent._client = None  # test fallback heuristic

    existing = {
        "Dockerfile": "FROM python:3.11\nEXPOSE 8080\n",
        "app/main.py": "from flask import Flask\napp = Flask(__name__)\n",
        "service.yaml": "apiVersion: serving.knative.dev/v1\n",
    }
    feedback = "Please change the container port to 5000 in Dockerfile"
    affected = agent._identify_affected_files(existing, feedback, "plan context")

    assert "modify" in affected
    assert "Dockerfile" in affected["modify"]
    # Unmentioned files should not be modified
    assert "app/main.py" not in affected["modify"]
    assert "service.yaml" not in affected["modify"]


def test_codegen_differential_spec_update_preserves_untouched_files():
    agent = CodeGeneratorAgent()
    agent._client = MagicMock()

    # Mock response for _identify_affected_files
    mock_classify_resp = MagicMock()
    mock_classify_resp.text = '{"modify": ["Dockerfile"], "create": [], "delete": []}'

    # Mock response for _modify_file_with_feedback
    mock_file_resp = MagicMock()
    mock_file_resp.text = "FROM python:3.11\nEXPOSE 5000\nCMD ['python', 'main.py']\n"

    agent._client.models.generate_content.side_effect = [
        mock_classify_resp,
        mock_file_resp,
    ]

    existing = {
        "Dockerfile": "FROM python:3.11\nEXPOSE 8080\n",
        "app/main.py": "from flask import Flask\napp = Flask(__name__)\n",
        "requirements.txt": "flask==3.0.0\n",
    }
    spec = {
        "title": "Order Service",
        "endpoints": [{"path": "/orders", "method": "GET"}],
    }

    diff = agent.generate_from_spec(
        spec=spec,
        target_platform="CloudRun",
        feedback="Change port to 5000 in Dockerfile",
        existing_files=existing,
    )

    assert isinstance(diff, CodeDiff)
    assert "Dockerfile" in diff.file_contents
    assert "app/main.py" in diff.file_contents
    # app/main.py and requirements.txt should retain their exact original contents
    assert diff.file_contents["app/main.py"] == existing["app/main.py"]
    assert diff.file_contents["requirements.txt"] == existing["requirements.txt"]
    # Dockerfile should have the new content
    assert "5000" in diff.file_contents["Dockerfile"]


@pytest.mark.anyio
async def test_async_supervisor_step_codegen_uses_existing_files():
    from src.orchestrator.supervisor import AsyncDevSecOpsSupervisor
    from src.orchestrator.state_manager import SessionStateManager

    state_mgr = SessionStateManager()
    session = state_mgr.create_session(["Analyze", "Propose", "CodeGen", "Infra", "Test"])
    # Simulate prior codegen data
    session.codegen_data = {
        "file_contents": {
            "Dockerfile": "FROM python:3.11\n",
            "app/healthz.py": "def healthz(): pass\n",
        }
    }

    supervisor = AsyncDevSecOpsSupervisor(session)
    plan = MigrationPlan(
        baseline=CostEstimate(platform="GCE", monthly_cost_usd=100.0, breakdown={}),
        target=CostEstimate(platform="CloudRun", monthly_cost_usd=30.0, breakdown={}),
        target_platform="CloudRun",
        monthly_savings_usd=70.0,
        savings_pct=70.0,
        rationale="Serverless cost optimization",
    )

    diff = await supervisor._step_codegen(plan, feedback="Add logging to healthz")
    assert isinstance(diff, CodeDiff)
    assert "Dockerfile" in diff.file_contents
    assert "app/healthz.py" in diff.file_contents
    assert "Revision requested" in diff.file_contents["app/healthz.py"]
    # Session codegen_data should be updated
    assert session.codegen_data is not None
    assert "file_contents" in session.codegen_data
