"""GCP API authentication & client initialization.

Description: Provides authenticated client instances for GCP services
             (Billing, Cloud Build, Artifact Registry, etc.).
Need: Every MCP server that calls a GCP API needs consistent credential
      handling (ADC, service account) rather than re-implementing auth.
Motive: Centralize GCP authentication so credentials are sourced once,
        consistently, and never hardcoded.
"""


def get_gcp_client(service_name: str):
    """Returns an authenticated client for the given GCP service."""
    raise NotImplementedError
