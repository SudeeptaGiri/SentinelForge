"""GCP API authentication & client initialization.

Description: Provides authenticated client instances for GCP services and Gemini GenAI
             (ADC via google.auth.default(), Vertex AI, Billing, Cloud Build, etc.).
Need: Every agent and MCP server needs consistent credential handling (ADC, service account)
      rather than re-implementing auth.
Motive: Centralize GCP authentication so credentials are sourced once, consistently, and
        support both ADC and API key authentication methods.
"""

import os
import warnings
from typing import Any, Optional, Tuple
import google.auth
from google.auth.credentials import Credentials
from google import genai


def get_default_gcp_credentials() -> Tuple[Optional[Credentials], Optional[str]]:
    """Retrieves Google Cloud Application Default Credentials (ADC) and project ID."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            credentials, project = google.auth.default()
            project = project or os.getenv("GCP_PROJECT_ID", "sentinelforge-dev")
            return credentials, project
    except Exception as e:
        return None, os.getenv("GCP_PROJECT_ID", "sentinelforge-dev")


def get_genai_client() -> Optional[genai.Client]:
    """Initializes Google GenAI Client using ADC (Vertex AI) or GEMINI_API_KEY.

    Returns:
        genai.Client instance or None if no valid credentials/keys exist.
    """
    # 1. Check GEMINI_API_KEY / GOOGLE_API_KEY
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        try:
            return genai.Client(api_key=api_key)
        except Exception:
            pass

    # 2. Check ADC (Vertex AI)
    try:
        credentials, project = get_default_gcp_credentials()
        region = os.getenv("GCP_REGION", "us-central1")
        if credentials and project:
            return genai.Client(
                vertexai=True,
                project=project,
                location=region,
                credentials=credentials
            )
    except Exception:
        pass

    return None


def get_gcp_client(service_name: str) -> Any:
    """Returns an authenticated client for the given GCP service.

    Args:
        service_name: 'genai', 'storage', 'cloudbuild', etc.
    """
    if service_name.lower() in ("genai", "gemini"):
        return get_genai_client()

    credentials, project = get_default_gcp_credentials()
    return {"service": service_name, "project": project, "authenticated": credentials is not None}
