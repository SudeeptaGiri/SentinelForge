"""ADK web dev-UI entrypoint exposing InfraBuilderAgent's underlying google-adk Agent."""

import os
import sys

# Repo root must be importable as `src.*` regardless of the cwd `adk web` is run from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.agents.infra_agent import InfraBuilderAgent

root_agent = InfraBuilderAgent().adk_agent
