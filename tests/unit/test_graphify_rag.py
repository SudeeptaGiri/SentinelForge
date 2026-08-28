"""Unit tests for Graphify GraphRAG engine and server_graphify MCP tools."""

import os
import pytest
from src.utils.graphify_rag import GraphifyKnowledgeGraph
from src.mcp_servers.server_graphify import (
    index_repository,
    query_codebase_graph,
    get_impact_analysis,
    get_architecture_summary,
    analyze_repository,
)

FIXTURE_PATH = "fixtures/sample_legacy_app"


def test_graphify_knowledge_graph_build():
    graph = GraphifyKnowledgeGraph(FIXTURE_PATH)
    graph.build_graph()

    summary = graph.get_summary()
    assert summary["detected_framework"] == "Flask"
    assert summary["detected_platform"] == "GCE"
    assert summary["is_stateful"] is False
    assert len(summary["routes"]) >= 4
    assert any("GET /health" in r for r in summary["routes"])
    assert any("POST /api/v1/orders" in r for r in summary["routes"])

    # Check workload profile extraction
    profile = summary["workload_profile"]
    assert profile["machine_type"] == "n1-standard-4"
    assert profile["cpu_cores"] == 4.0
    assert profile["ram_gb"] == 16.0
    assert profile["disk_gb"] == 50.0
    assert profile["has_autoscaling"] is False


def test_graphify_query_and_impact():
    graph = GraphifyKnowledgeGraph(FIXTURE_PATH)
    graph.build_graph()

    query_res = graph.query("orders")
    assert query_res["total_matches"] > 0
    assert any("orders" in node["name"].lower() for node in query_res["top_nodes"])

    impact_res = graph.get_impact_analysis("query_orders")
    assert impact_res["target"] == "query_orders"
    assert len(impact_res["callers"]) >= 2
    assert any("list_orders" in c for c in impact_res["callers"])


def test_mcp_server_graphify_functions():
    index_res = index_repository(FIXTURE_PATH)
    assert index_res["status"] == "success"

    arch = get_architecture_summary(FIXTURE_PATH)
    assert arch["detected_framework"] == "Flask"

    impact = get_impact_analysis("get_db_connection")
    assert "target" in impact

    analysis = analyze_repository(FIXTURE_PATH)
    assert analysis["status"] == "success"
    assert analysis["detected_framework"] == "Flask"
    assert analysis["detected_platform"] == "GCE"
    assert analysis["routes_count"] >= 4


def test_mcp_server_graphify_error_handling():
    # Invalid local path
    res = index_repository("invalid/nonexistent/directory/path")
    assert res["status"] == "error"
    assert "error" in res

    # Unauthorized SSRF host
    res_ssrf = index_repository("https://unauthorized-host.internal/repo.git")
    assert res_ssrf["status"] == "error"
    assert "not authorized" in res_ssrf["error"]
