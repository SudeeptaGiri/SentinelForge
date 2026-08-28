"""MCP Server: Strix DAST/SAST Scanner Wrapper.

Description: MCP tool server wrapping the Strix security scanner CLI
             (`run_strix_dast_scan`). For the hackathon demo this returns
             realistic, deterministic mock findings — the safety checks
             (host allowlist, forbidden actions, intensity clamp) are real
             and enforced from `config/security_rules.yaml`, so swapping in
             the real Strix CLI later is a drop-in change behind this
             function boundary.
Need: The Pentest Agent must trigger scans against staging targets in a
      controlled, auditable way that respects `security_rules.yaml` and
      never touches production hosts.
Motive: Keep the Strix CLI invocation and its safety checks (allowlists,
        intensity thresholds) in one place, separate from agent reasoning.
"""

from __future__ import annotations

import fnmatch
import hashlib
import random
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml
from mcp.server.fastmcp import FastMCP

# Real MCP server: exposes this module's tool(s) over stdio/SSE so an ADK
# `MCPToolset` (or any MCP client) can call it, per the Stream 2 "Custom Agent
# + MCP" requirement. Run standalone with `python -m src.mcp_servers.server_strix`.
server = FastMCP("strix-mcp")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "security_rules.yaml"

_MOCK_FINDING_POOL = [
    {"title": "Missing HTTP Strict-Transport-Security header", "cvss_score": 3.1, "description": "The response does not set HSTS, allowing potential protocol downgrade attacks."},
    {"title": "Verbose stack trace on 500 error", "cvss_score": 5.3, "description": "An internal error page leaks framework version and file paths."},
    {"title": "Outdated TLS cipher suite offered", "cvss_score": 4.8, "description": "Server negotiates a legacy cipher suite that should be disabled."},
    {"title": "Session cookie missing Secure/HttpOnly flags", "cvss_score": 6.5, "description": "Session cookie can be read by client-side scripts or sent over plaintext HTTP."},
]

# Only surfaced at "high" intensity, so the default demo (medium) is always a
# reliable, non-blocking happy path, while "high" still demonstrates the
# release-blocking behavior for a critical finding.
_HIGH_INTENSITY_ONLY_FINDINGS = [
    {"title": "Unauthenticated actuator/debug endpoint exposed", "cvss_score": 8.6, "description": "A debug endpoint reveals environment variables without authentication."},
    {"title": "SQL error message reflects raw query", "cvss_score": 9.1, "description": "A malformed input reflects a raw SQL error, indicating possible injection risk."},
]


class SecurityPolicyError(RuntimeError):
    """Raised when a scan request violates `config/security_rules.yaml`."""


@lru_cache(maxsize=1)
def _load_security_rules() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["security"]


def _assert_allowlisted(target_url: str) -> None:
    host = urlparse(target_url).hostname or target_url
    rules = _load_security_rules()

    # Explicitly blocked hosts take priority over allowlist.
    blocked = rules.get("blocked_hosts", [])
    if any(fnmatch.fnmatch(host, pattern) for pattern in blocked):
        raise SecurityPolicyError(
            f"Refusing to scan '{host}': explicitly blocked in security_rules.yaml blocked_hosts"
        )

    patterns = rules.get("allowlisted_hosts", [])
    if not any(fnmatch.fnmatch(host, pattern) for pattern in patterns):
        raise SecurityPolicyError(
            f"Refusing to scan '{host}': not in security_rules.yaml allowlisted_hosts {patterns}"
        )


def _clamp_intensity(intensity: str) -> str:
    rules = _load_security_rules()
    allowed = ["low", "medium", "high"]
    max_allowed = rules.get("dast_intensity", "medium")
    if intensity not in allowed:
        intensity = "medium"
    # Never exceed the configured ceiling, regardless of caller input.
    return intensity if allowed.index(intensity) <= allowed.index(max_allowed) else max_allowed


def run_strix_dast_scan(target_url: str, intensity: str = "medium") -> dict:
    """Runs a (mocked) Strix DAST scan against an allowlisted staging target.

    Deterministic: the same `target_url` always yields the same finding set,
    so the demo's self-heal/pentest narrative is reproducible in front of
    judges rather than left to random chance.
    """
    _assert_allowlisted(target_url)
    intensity = _clamp_intensity(intensity)

    seed = int(hashlib.sha256(target_url.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    pool = _MOCK_FINDING_POOL + (_HIGH_INTENSITY_ONLY_FINDINGS if intensity == "high" else [])
    finding_count = {"low": 1, "medium": 2, "high": 3}[intensity]
    findings = rng.sample(pool, k=min(finding_count, len(pool)))

    return {
        "target_url": target_url,
        "intensity": intensity,
        "findings": findings,
    }


@server.tool(name="strix_dast_scan")
def strix_dast_scan_tool(target_url: str, intensity: str = "medium") -> dict:
    """MCP tool entrypoint: run an allowlisted Strix DAST scan and return CVSS findings."""
    return run_strix_dast_scan(target_url, intensity)


if __name__ == "__main__":
    # stdio transport for local ADK MCPToolset wiring; use `server.run(transport="sse")`
    # (behind Cloud Run + IAP) when registering this server with Vertex AI Agent Engine.
    server.run()

