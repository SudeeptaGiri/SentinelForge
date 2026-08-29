"""MCP Server: Graphify AST & Codebase GraphRAG.

Description: MCP tool server exposing codebase AST graph search, repository
             indexing, call hierarchy extraction, and blast-radius impact analysis.
Need: The Analysis Agent and Code Generator Agent need a stable tool interface to query
      codebase structure without embedding Graphify's internal parser directly.
Motive: Decouple graph extraction logic behind standard MCP tools so it can be upgraded
        or replaced independently.
"""

from typing import Any, Dict, Optional
from src.utils.graphify_rag import GraphifyKnowledgeGraph

# Module-level graph cache
_ACTIVE_GRAPH: Optional[GraphifyKnowledgeGraph] = None
_ACTIVE_REPO_TARGET: Optional[str] = None


def index_repository(repo_path_or_url: str) -> Dict[str, Any]:
    """Indexes a repository codebase from a local directory OR remote Git URL (e.g. 'https://github.com/org/repo.git').
    Remote Git URLs are automatically cloned and indexed.

    Args:
        repo_path_or_url: Local directory path OR remote Git URL (GitHub, GitLab, Bitbucket).

    Returns:
        Structured summary of the indexed codebase knowledge graph, or error dict.
    """
    global _ACTIVE_GRAPH, _ACTIVE_REPO_TARGET
    try:
        if _ACTIVE_REPO_TARGET == repo_path_or_url and _ACTIVE_GRAPH is not None:
            return {
                "status": "success",
                "message": f"Using cached index for repository '{repo_path_or_url}'",
                "summary": _ACTIVE_GRAPH.get_summary()
            }
        graph = GraphifyKnowledgeGraph(repo_path_or_url)
        graph.build_graph()
        _ACTIVE_GRAPH = graph
        _ACTIVE_REPO_TARGET = repo_path_or_url
        return {
            "status": "success",
            "message": f"Successfully indexed repository from '{repo_path_or_url}'",
            "summary": graph.get_summary()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "summary": {}
        }


def query_codebase_graph(query: str, repo_path_or_url: Optional[str] = None) -> Dict[str, Any]:
    """Executes a GraphRAG search over the indexed codebase knowledge graph.

    Args:
        query: Keyword or natural-language query to locate symbols, routes, or components.
        repo_path_or_url: Optional local directory path OR remote Git URL if not already indexed.

    Returns:
        Matched graph nodes, score, and architectural context.
    """
    global _ACTIVE_GRAPH, _ACTIVE_REPO_TARGET
    if repo_path_or_url and (_ACTIVE_REPO_TARGET != repo_path_or_url or _ACTIVE_GRAPH is None):
        index_res = index_repository(repo_path_or_url)
        if index_res.get("status") == "error":
            return index_res

    if _ACTIVE_GRAPH is None:
        return {"error": "No repository has been indexed yet. Call index_repository or pass repo_path_or_url."}

    return _ACTIVE_GRAPH.query(query)


def get_impact_analysis(target_symbol: str) -> Dict[str, Any]:
    """Calculates blast-radius and callers/dependencies for a symbol or file.

    Args:
        target_symbol: Function name, class name, or file to analyze.

    Returns:
        Blast-radius score, direct callers, and dependencies.
    """
    global _ACTIVE_GRAPH
    if _ACTIVE_GRAPH is None:
        return {"error": "No repository has been indexed yet. Call index_repository first."}

    return _ACTIVE_GRAPH.get_impact_analysis(target_symbol)


def get_architecture_summary(repo_path_or_url: Optional[str] = None) -> Dict[str, Any]:
    """Returns the comprehensive architectural summary of the codebase.
    Supports both local filesystem directories and remote Git URLs (e.g. 'https://github.com/org/repo.git').

    Args:
        repo_path_or_url: Optional local directory path OR remote Git URL. If not indexed, automatically clones and indexes it.

    Returns:
        Structured architecture summary including detected framework, platform,
        workload profile, routes, and infrastructure specs.
    """
    global _ACTIVE_GRAPH, _ACTIVE_REPO_TARGET
    if repo_path_or_url and (_ACTIVE_REPO_TARGET != repo_path_or_url or _ACTIVE_GRAPH is None):
        index_res = index_repository(repo_path_or_url)
        if index_res.get("status") == "error":
            return index_res

    if _ACTIVE_GRAPH is None:
        return {"error": "No repository has been indexed yet. Call index_repository or provide repo_path_or_url."}

    return _ACTIVE_GRAPH.get_summary()


def analyze_repository(repo_path_or_url: str) -> Dict[str, Any]:
    """Performs end-to-end architectural and infrastructure analysis on a local directory OR remote Git URL.
    Automatically clones remote Git repositories, analyzes AST, call hierarchy, framework, and produces
    workload profiling for cloud modernization.

    Args:
        repo_path_or_url: Local directory path OR remote Git URL (e.g. 'https://github.com/SudeeptaGiri/spill-the-tea.git').

    Returns:
        Complete architecture summary, detected platform, routes count, and workload profile.
    """
    index_res = index_repository(repo_path_or_url)
    if index_res.get("status") == "error":
        return index_res

    summary = index_res.get("summary", {})
    return {
        "status": "success",
        "target": repo_path_or_url,
        "was_cloned": summary.get("was_cloned", False),
        "detected_framework": summary.get("detected_framework", "Unknown"),
        "detected_platform": summary.get("detected_platform", "Unknown"),
        "is_stateful": summary.get("is_stateful", False),
        "total_files": summary.get("total_files", 0),
        "routes_count": summary.get("routes_count", 0),
        "routes": summary.get("routes", []),
        "dependencies": summary.get("dependencies", []),
        "workload_profile": summary.get("workload_profile", {}),
        "summary": summary
    }


def mcp_graphify_query(query: str) -> Dict[str, Any]:
    """Legacy wrapper for mcp_graphify_query executing search against active graph."""
    return query_codebase_graph(query)
