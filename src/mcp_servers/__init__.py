"""Model Context Protocol (MCP) Tool Servers package.

Description: Contains MCP servers that expose external tools (Graphify,
             Strix, GCP Billing, Cloud Build, Git) to the agents.
Need: Agents must call real external systems (scanners, APIs, CLIs) through
      a standard, auditable protocol rather than ad-hoc SDK calls scattered
      across agent code.
Motive: Centralize tool access behind MCP so tools are swappable, mockable
        for tests, and consistently permissioned.
"""
