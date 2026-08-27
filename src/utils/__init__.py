"""Shared Utilities & Helpers package.

Description: Cross-cutting helpers (GCP auth, logging, templating) used by
             agents and MCP servers.
Need: Avoid duplicating boilerplate (client init, logging setup, template
      rendering) across every agent/server module.
Motive: Keep infrastructure-level concerns out of business logic.
"""
