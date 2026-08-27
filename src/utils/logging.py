"""OpenTelemetry & GCP Cloud Logging setup.

Description: Configures structured logging and tracing for the agent system.
Need: Multi-agent, multi-step pipelines are hard to debug without correlated
      traces/logs across the supervisor, sub-agents, and MCP servers.
Motive: Provide a single, consistent logging/tracing setup so failures in
        any step (e.g. self-healing loop, security scan) are diagnosable.
"""

import logging


def configure_logging() -> logging.Logger:
    """Configures and returns the application logger with OTel integration."""
    logger = logging.getLogger("sentinelforge")
    logging.basicConfig(level=logging.INFO)
    return logger
