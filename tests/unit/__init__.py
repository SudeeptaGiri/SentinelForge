"""Unit test suite for agents & MCP tools.

Description: Isolated unit tests covering individual agent and MCP server
             functions in isolation (mocked dependencies).
Need: Each specialist agent's logic must be verifiable independently of the
      full pipeline and external GCP/Strix/Graphify calls.
Motive: Catch regressions in single units of behavior quickly and cheaply.
"""
