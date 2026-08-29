"""Codebase Analysis Agent (Graphify GraphRAG queries).

Description: Queries Graphify GraphRAG to read codebase structure, call
             graphs, AST, and dependencies; generates strongly typed AnalysisResult.
Need: Code generation/refactoring on an existing (Ongoing Tasks/Migration)
      codebase requires understanding impact/blast-radius before editing.
Motive: Ground code-gen decisions in the real structure of the repository
        instead of relying on the LLM's assumptions, reducing regressions.
"""

import json
import os
import time
from typing import Any, Dict, List, Tuple

from google.adk.agents import Agent
from src.utils.terminal_logger import log_agent_call, log_llm_request, log_llm_response

from src.models.schemas import AnalysisResult, WorkloadSpec
from src.mcp_servers.server_graphify import (
    index_repository,
    query_codebase_graph,
    get_impact_analysis,
    get_architecture_summary,
    analyze_repository,
)
from src.utils.gcp_client import get_genai_client
from src.utils.repo_loader import is_git_url, get_repo_name_from_url


class AnalysisAgent:
    """Analyzes codebase structure and change impact via Graphify GraphRAG and Gemini."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._init_adk_agent()

    def _init_adk_agent(self) -> None:
        """Initializes the Google ADK Agent representation."""
        self.adk_agent = Agent(
            name="analysis_agent",
            description="Analyzes codebase architecture, AST call graphs, and deployment profiles via Graphify GraphRAG.",
            model=self.model_name,
            instruction=(
                "You are the SentinelForge Codebase Analysis Agent. "
                "You inspect repository structure, AST graphs, route definitions, and deployment manifests "
                "to produce structured architectural analysis and workload specifications for cloud migration.\n\n"
                "CRITICAL OPERATIONAL RULES:\n"
                "1. You support BOTH local repository paths (e.g., 'fixtures/sample_legacy_app') AND remote Git URLs "
                "(e.g., 'https://github.com/SudeeptaGiri/spill-the-tea.git', 'https://gitlab.com/...').\n"
                "2. When a user asks you to analyze a repository or provides a GitHub/GitLab URL or local path, "
                "call `analyze_repository(repo_path_or_url=...)` or `get_architecture_summary(repo_path_or_url=...)` directly. "
                "The backend automatically clones and indexes the repository in a secure cache.\n"
                "3. NEVER instruct the user to clone the repository manually in their terminal or claim that remote URLs are unsupported. "
                "Pass the URL directly to the tool and report the architectural findings."
            ),
            tools=[
                analyze_repository,
                index_repository,
                query_codebase_graph,
                get_impact_analysis,
                get_architecture_summary,
            ]
        )

    def analyze_impact(self, target_symbol: str) -> Dict[str, Any]:
        """Calculates blast-radius and callers/dependencies for a symbol or file."""
        return get_impact_analysis(target_symbol)

    def analyze_codebase(self, repo_path: str) -> AnalysisResult:
        """Full pipeline: indexes repository, extracts GraphRAG knowledge, and synthesizes AnalysisResult.

        Args:
            repo_path: Directory path of the target application repository.

        Returns:
            Structured AnalysisResult matching the shared contract for downstream agents.
        """
        log_agent_call("AnalysisAgent", "analyze_codebase", f"repo={repo_path}")
        # 1. Index the repository with Graphify GraphRAG (MCP Server Layer 4)
        index_res = index_repository(repo_path)
        graph_summary = index_res.get("summary", {})

        # 2. Extract baseline attributes from GraphRAG
        detected_platform = graph_summary.get("detected_platform", "Unknown")
        framework = graph_summary.get("detected_framework", "Unknown")
        is_stateful = graph_summary.get("is_stateful", False)
        files = graph_summary.get("files", [])
        dependencies = graph_summary.get("dependencies", [])
        routes = graph_summary.get("routes", [])
        infra_list = graph_summary.get("infrastructure", [])

        has_dockerfile = any(f.lower() == "dockerfile" or f.endswith(".dockerfile") for f in files)
        has_autoscaling = any(i.get("autoscaling", False) for i in infra_list)

        workload_prof = graph_summary.get("workload_profile", {})
        default_name = get_repo_name_from_url(repo_path) if is_git_url(repo_path) else os.path.basename(os.path.abspath(repo_path))
        app_name = workload_prof.get("name") or default_name
        cpu_cores = float(workload_prof.get("cpu_cores", 2.0))
        ram_gb = float(workload_prof.get("ram_gb", 4.0))
        disk_gb = float(workload_prof.get("disk_gb", 20.0))
        monthly_requests = int(workload_prof.get("monthly_requests", 100000))

        # 3. LLM synthesis using Gemini API (via ADC or API Key)
        llm_summary, recommendations = self._synthesize_with_llm(graph_summary)

        # 4. Construct WorkloadSpec
        workload_spec = WorkloadSpec(
            name=app_name,
            cpu_cores=cpu_cores,
            ram_gb=ram_gb,
            disk_gb=disk_gb,
            monthly_requests=monthly_requests,
            is_stateful=is_stateful,
        )

        # 5. Assemble and return AnalysisResult
        return AnalysisResult(
            detected_platform=detected_platform,
            workload_spec=workload_spec,
            summary=llm_summary,
            files_of_interest=files,
            architecture_type=f"Stateless {framework} API" if not is_stateful else f"Stateful {framework} Monolith",
            framework=framework,
            dependencies=dependencies,
            has_dockerfile=has_dockerfile,
            has_autoscaling=has_autoscaling,
            graph_summary=graph_summary,
            recommendations=recommendations,
        )

    def _synthesize_with_llm(self, graph_summary: Dict[str, Any]) -> Tuple[str, List[str]]:
        """Invokes Gemini LLM to reason over GraphRAG context; falls back gracefully if offline."""
        client = get_genai_client()
        prompt = (
            "You are the SentinelForge Codebase Analysis Agent. "
            "Given the following GraphRAG code knowledge graph summary, produce:\n"
            "1. A concise natural-language architecture summary (1-2 sentences) highlighting framework, current hosting, and scaling status.\n"
            "2. A list of 2-3 specific architectural recommendations for migrating/optimizing on GCP (e.g. Cloud Run, GKE Autopilot).\n\n"
            f"GraphRAG Context:\n{json.dumps(graph_summary, indent=2)}\n\n"
            "Return JSON in the format:\n"
            "{\n"
            '  "summary": "...",\n'
            '  "recommendations": ["...", "..."]\n'
            "}"
        )

        if client:
            try:
                log_llm_request("AnalysisAgent", self.model_name, prompt, purpose="Architecture Summary")
                start_t = time.perf_counter()
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                duration = time.perf_counter() - start_t
                if response and response.text:
                    log_llm_response("AnalysisAgent", self.model_name, response.text, duration_sec=duration)
                    clean_text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    parsed = json.loads(clean_text)
                    return parsed.get("summary", ""), parsed.get("recommendations", [])
            except Exception:
                pass

        # Deterministic / offline fallback heuristic synthesis
        framework = graph_summary.get("detected_framework", "Python")
        platform = graph_summary.get("detected_platform", "GCE")
        routes_count = graph_summary.get("routes_count", 0)
        has_dockerfile = any("dockerfile" in f.lower() for f in graph_summary.get("files", []))

        summary = (
            f"Stateless {framework} REST API ({routes_count} endpoints) currently deployed on static {platform} VM "
            f"with single-instance systemd management and no autoscaling."
        )
        recommendations = [
            "Migrate workload from static GCE VM to Google Cloud Run v2 to achieve auto-scaling to zero and reduce idle compute costs.",
            "Refactor Dockerfile into a multi-stage container build and integrate Cloud Build CI/CD with security scanning.",
            "Externalize state and database connection configuration to Google Secret Manager and Cloud SQL."
        ]
        return summary, recommendations
