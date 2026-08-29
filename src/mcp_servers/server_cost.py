"""MCP Server: GCP Architecture Cost Estimator.

Description: FastMCP tool server wrapping CostScalingAgent.estimate_from_architecture().
             Accepts a free-text architecture description and returns a full monthly
             USD cost breakdown per GCP service type.
Need: ADK agents (MCPToolset) and the web API route need a single, consistent
      interface for cost estimation without re-implementing the pricing logic.
Motive: Expose the same pricing engine both as a standalone MCP stdio server
        (for ADK agent composition) and as a callable used directly by the
        FastAPI route (same process, no transport overhead).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.agents.cost_agent import CostScalingAgent

server = FastMCP("gcp-cost-mcp")

# Module-level singleton so every call reuses the Gemini client (if configured).
_agent = CostScalingAgent()


def estimate_architecture_cost(
    architecture_text: str, region: str = "us-central1"
) -> dict:
    """Parse architecture_text and return a monthly GCP cost estimate as a dict."""
    result = _agent.estimate_from_architecture(architecture_text, region)
    return result.model_dump()


@server.tool(name="estimate_architecture_cost")
def estimate_architecture_cost_tool(
    architecture_text: str, region: str = "us-central1"
) -> dict:
    """MCP tool: estimate monthly GCP running cost from a free-text architecture description.

    Args:
        architecture_text: Plain-English description of the GCP architecture,
            e.g. "3 Cloud Run services (2 vCPU, 1 GB RAM each), 1 Cloud SQL
            db-n1-standard-2, 500 GB GCS bucket, 5M Pub/Sub messages/month".
        region: GCP region for pricing (default: us-central1).

    Returns:
        Dict with keys: services (list), total_monthly_cost_usd (float),
        region (str), parsed_services_count (int), disclaimer (str).
    """
    return estimate_architecture_cost(architecture_text, region)


if __name__ == "__main__":
    # stdio transport for local ADK MCPToolset wiring.
    # Use server.run(transport="sse") behind Cloud Run + IAP for Vertex AI Agent Engine.
    server.run()
