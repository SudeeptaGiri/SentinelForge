"""Terminal logging utilities for real-time Agent and LLM visibility.

Description: Provides lightweight, colorized, minimal terminal logs that highlight:
             - Which agent is being called and its action
             - LLM request prompts, targets, and purpose
             - LLM response latency, output size, and content preview
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from typing import Any

logger = logging.getLogger("sentinelforge.terminal")

# ANSI color codes
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Enable color if running in terminal and NO_COLOR is not set
USE_COLOR = os.environ.get("NO_COLOR") is None


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}" if USE_COLOR else text


def _clean_preview(text: str, max_chars: int = 140) -> str:
    """Cleans up prompt or response text for a compact single-line terminal preview."""
    if not text:
        return "<empty>"
    # Remove markdown code fence markers and clean whitespace
    cleaned = re.sub(r"```[a-zA-Z]*", "", str(text))
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_chars:
        return cleaned[:max_chars].strip() + "…"
    return cleaned


def log_agent_call(agent_name: str, action: str, details: str = "") -> None:
    """Logs an agent invocation in the terminal.

    Example:
        [AGENT] 🤖 SpecAgent | Action: generate_api_specification | Details: target=CloudRun
    """
    badge = _c(CYAN + BOLD, "[AGENT]")
    agent_tag = _c(BOLD, f"🤖 {agent_name}")
    action_tag = _c(CYAN, f"Action: {action}")
    details_tag = f"| {DIM}{details}{RESET}" if details else ""
    
    msg = f"{badge} {agent_tag} | {action_tag} {details_tag}"
    print(msg, flush=True)
    logger.info("Agent call: %s -> %s (%s)", agent_name, action, details)


def log_llm_request(
    agent_name: str,
    model: str,
    prompt: Any,
    purpose: str = "",
) -> None:
    """Logs an LLM request dispatch in the terminal.

    Example:
        [LLM REQ] 📤 [SpecAgent -> gemini-2.5-pro] Purpose: OpenAPI Contract (Prompt: 512 chars)
                  Preview: "You are the SentinelForge Spec Alignment Agent..."
    """
    badge = _c(YELLOW + BOLD, "[LLM REQ]")
    caller = _c(YELLOW, f"📤 [{agent_name} -> {model}]")
    purpose_str = f"Purpose: {purpose} " if purpose else ""
    prompt_str = str(prompt)
    size_str = f"({len(prompt_str):,} chars)"
    preview = _clean_preview(prompt_str)

    line1 = f"{badge} {caller} {purpose_str}{DIM}{size_str}{RESET}"
    line2 = f"          {DIM}Preview:{RESET} \"{preview}\""
    print(f"{line1}\n{line2}", flush=True)
    logger.info("LLM REQ: %s -> %s (purpose=%s, chars=%d)", agent_name, model, purpose, len(prompt_str))


def log_llm_response(
    agent_name: str,
    model: str,
    response_text: Any,
    duration_sec: float | None = None,
) -> None:
    """Logs an LLM response receipt in the terminal.

    Example:
        [LLM RES] 📥 [SpecAgent <- gemini-2.5-pro] in 1.4s (Output: 1,240 chars)
                  Preview: "openapi: 3.1.0 info: title: Payments API..."
    """
    badge = _c(GREEN + BOLD, "[LLM RES]")
    caller = _c(GREEN, f"📥 [{agent_name} <- {model}]")
    time_str = f"in {duration_sec:.2f}s " if duration_sec is not None else ""
    resp_str = str(response_text or "")
    size_str = f"({len(resp_str):,} chars)"
    preview = _clean_preview(resp_str)

    line1 = f"{badge} {caller} {time_str}{DIM}{size_str}{RESET}"
    line2 = f"          {DIM}Preview:{RESET} \"{preview}\""
    print(f"{line1}\n{line2}", flush=True)
    logger.info("LLM RES: %s <- %s (duration=%.2fs, chars=%d)", agent_name, model, duration_sec or 0.0, len(resp_str))


class LLMTimer:
    """Context manager / helper to record LLM call duration."""

    def __init__(self, agent_name: str, model: str, prompt: Any, purpose: str = "") -> None:
        self.agent_name = agent_name
        self.model = model
        self.prompt = prompt
        self.purpose = purpose
        self.start_time: float = 0.0

    def __enter__(self) -> LLMTimer:
        log_llm_request(self.agent_name, self.model, self.prompt, self.purpose)
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def log_response(self, response_text: Any) -> None:
        duration = time.perf_counter() - self.start_time if self.start_time else None
        log_llm_response(self.agent_name, self.model, response_text, duration_sec=duration)


def log_gate_waiting(step_id: int, gate_name: str, summary: str = "", timeout_sec: int = 300) -> None:
    """Logs a prominent alert when a HITL gate is paused and waiting for human approval."""
    bar = "=" * 72
    badge = _c(YELLOW + BOLD, "🛑 HITL GATE WAITING FOR APPROVAL")
    step_info = _c(BOLD, f"Step {step_id}: {gate_name}")
    action_info = _c(CYAN + BOLD, "👉 Action Required: Click 'Approve' in Web UI or enter 'y' in Terminal!")
    summary_preview = f"   Summary: {summary[:120]}..." if summary else ""
    timeout_info = _c(DIM, f"   (Timeout: {timeout_sec}s - auto-rejects if unattended)")

    lines = [
        "",
        _c(YELLOW, bar),
        f"  {badge} -> {step_info}",
        f"  {action_info}",
        summary_preview,
        timeout_info,
        _c(YELLOW, bar),
        "",
    ]
    print("\n".join(l for l in lines if l != ""), flush=True)
    logger.info("Gate waiting: step %d (%s) - timeout %ds", step_id, gate_name, timeout_sec)


def log_gate_decision(step_id: int, gate_name: str, approved: bool, feedback: str = "", duration_sec: float = 0.0) -> None:
    """Logs a gate decision receipt."""
    badge = _c(GREEN + BOLD if approved else MAGENTA + BOLD, "[GATE DECISION]")
    status_str = _c(GREEN + BOLD if approved else MAGENTA + BOLD, "APPROVED" if approved else "REJECTED")
    feedback_str = f" | Feedback: {feedback}" if feedback else ""
    msg = f"{badge} Step {step_id} ({gate_name}) -> {status_str} (waited {duration_sec:.1f}s){feedback_str}"
    print(msg, flush=True)
    logger.info("Gate decision: %d (%s) -> %s", step_id, gate_name, "APPROVED" if approved else "REJECTED")
