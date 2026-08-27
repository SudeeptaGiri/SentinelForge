"""MCP Server: Strix DAST/SAST Scanner Wrapper.

Description: MCP tool server wrapping Strix security scanner CLI
             (`run_strix_dast_scan`).
Need: The Pentest Agent must trigger real scans against staging targets in
      a controlled, auditable way that respects `security_rules.yaml`.
Motive: Keep the Strix CLI invocation and its safety checks (allowlists,
        intensity thresholds) in one place, separate from agent reasoning.
"""

server = None  # Server("strix-mcp") — placeholder until MCP SDK is wired in.


def run_strix_dast_scan(target_url: str, intensity: str = "medium") -> dict:
    """Runs a Strix DAST scan against an allowlisted staging target."""
    raise NotImplementedError
