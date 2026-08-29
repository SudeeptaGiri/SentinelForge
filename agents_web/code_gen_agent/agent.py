"""ADK web dev-UI entrypoint exposing CodeGeneratorAgent's underlying google-adk Agent."""

import os
import sys

# Repo root must be importable as `src.*` regardless of the cwd `adk web` is run from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.agents.code_gen_agent import CodeGeneratorAgent

root_agent = CodeGeneratorAgent().adk_agent
