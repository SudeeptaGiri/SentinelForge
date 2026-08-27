"""MCP Server: Graphify AST & Codebase GraphRAG.

Description: MCP tool server exposing codebase AST graph search
             (`mcp_graphify_query`).
Need: The Analysis Agent needs a stable tool interface to query codebase
      structure without embedding Graphify's internal API directly.
Motive: Isolate the Graphify integration behind MCP so it can be upgraded
        or replaced without touching agent logic.
"""

server = None  # Server("graphify-mcp") — placeholder until MCP SDK is wired in.


def mcp_graphify_query(query: str) -> dict:
    """Executes a GraphRAG query against the indexed codebase graph."""
    raise NotImplementedError
