"""ADC-first Gemini GenAI client builder shared by code-gen/QA/review agents.

Description: Builds an authenticated `google.genai.Client` preferring
             Application Default Credentials (Vertex AI), returning the
             auth mode so callers can enforce "ADC only" policies.
Need: CodeGeneratorAgent, QAAgent, ReviewAgent, and CodeOptimizerAgent all
      require a client + auth-mode + project tuple to gate whether they run.
Motive: Avoid duplicating ADC/API-key fallback logic across every agent.
"""

from __future__ import annotations

import os
import warnings
from typing import Optional, Tuple

from google import genai

from src.utils.gcp_client import get_default_gcp_credentials


def build_genai_client(
    api_key: Optional[str] = None,
) -> Tuple[Optional[genai.Client], Optional[str], Optional[str]]:
    """Builds a Gemini GenAI client, preferring ADC (Vertex AI) over API keys.

    Args:
        api_key: Optional explicit API key. Agents that require ADC-only
            auth ignore the returned client unless auth_mode == "adc".

    Returns:
        Tuple of (client, auth_mode, project) where auth_mode is "adc",
        "api_key", or None if no credentials were available.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        credentials, project = get_default_gcp_credentials()

    if credentials and project:
        try:
            region = os.getenv("GCP_REGION", "us-central1")
            client = genai.Client(
                vertexai=True,
                project=project,
                location=region,
                credentials=credentials,
            )
            return client, "adc", project
        except Exception:
            pass

    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key:
        try:
            return genai.Client(api_key=key), "api_key", None
        except Exception:
            pass

    return None, None, None
