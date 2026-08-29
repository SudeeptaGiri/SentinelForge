"""Supervisor-level Gemini calls with a deterministic fallback.

Description: Wraps the google-genai SDK for two supervisor tasks: classifying
             user intent and summarizing a step artifact for a HITL gate. If no
             API key or SDK is available (or a call fails), falls back to a
             deterministic template so the pipeline never breaks.
"""

from __future__ import annotations

import logging
import os
import time

from src.utils.terminal_logger import log_agent_call, log_llm_request, log_llm_response

logger = logging.getLogger(__name__)


def build_genai_client(api_key: str | None = None, model: str | None = None) -> tuple[any, str, str | None]:
    selected_model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, selected_model, None
    try:
        from google import genai  # guarded: optional dependency
        return genai.Client(api_key=key), selected_model, key
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        logger.warning("Gemini SDK unavailable (%s); using template fallback", exc)
        return None, selected_model, None


class GeminiClient:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self._client, self._model, self._api_key = build_genai_client(api_key=api_key, model=model)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def classify_intent(self, user_input: str) -> str:
        # Demo scope is hard-limited to the migration/cost scenario. A real
        # deployment would ask the model to choose among scenarios here.
        return "migration_cost"

    def summarize_for_gate(self, step_name: str, artifact: dict) -> str:
        if not self.enabled:
            return self._template_summary(step_name, artifact)
        try:
            prompt = (
                "Summarize this DevSecOps pipeline step result for a human "
                f"approval gate in 2-3 sentences.\nStep: {step_name}\n"
                f"Result: {artifact}"
            )
            log_llm_request("GeminiClient", self._model, prompt, purpose=f"Gate Summary ({step_name})")
            start_t = time.perf_counter()
            resp = self._client.models.generate_content(model=self._model, contents=prompt)
            duration = time.perf_counter() - start_t
            log_llm_response("GeminiClient", self._model, resp.text, duration_sec=duration)
            return (resp.text or "").strip() or self._template_summary(step_name, artifact)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash
            logger.warning("Gemini call failed (%s); using template fallback", exc)
            return self._template_summary(step_name, artifact)

    @staticmethod
    def _template_summary(step_name: str, artifact: dict) -> str:
        details = ", ".join(f"{k}={v}" for k, v in artifact.items()) or "no details"
        return f"[{step_name}] Review the result before approving: {details}."
