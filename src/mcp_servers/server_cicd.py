"""MCP Server: Cloud Build & Artifact Registry CLI Wrapper.

Description: MCP tool server wrapping Cloud Build & Artifact Registry
             (`trigger_cloud_build`).
Need: The QA and Infra agents need to build, test, and deploy containers in
      ephemeral sandboxes and production without embedding gcloud CLI logic
      directly in agent code.
Motive: Provide one governed entrypoint for all CI/CD actions (build, test,
        deploy) so pipeline behavior is consistent and auditable.
"""

server = None  # Server("cicd-mcp") — placeholder until MCP SDK is wired in.


def trigger_cloud_build(config_path: str, substitutions: dict | None = None) -> dict:
    """Triggers a Cloud Build pipeline run and returns the build status."""
    raise NotImplementedError
