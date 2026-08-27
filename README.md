# SentinelForge — Autonomous AI DevSecOps Agent

## Description

SentinelForge is an autonomous, multi-agent DevSecOps system built on Google Cloud
that takes a project idea, a bug ticket, or an existing repository and carries it
end-to-end through analysis, code generation, cost/infra planning, testing with
self-healing, security auditing, and production deployment — with human-in-the-loop
(HITL) approval gates at every critical decision point.

## Need

Modern software delivery requires coordinating many specialized concerns (spec
alignment, code generation, cost control, infrastructure provisioning, QA, and
security) that are usually handled by separate teams and tools. This creates
hand-off delays, inconsistent security posture, and unpredictable cloud costs.

## Motive

Provide a single orchestrated agent system (ADK Supervisor + specialist
sub-agents + MCP tool servers) that automates the full software delivery
lifecycle while keeping a human firmly in control via explicit confirmation
gates, reducing time-to-production without sacrificing safety or governance.

## Quickstart

1. Copy `.env.example` to `.env` and fill in `GCP_PROJECT_ID` / `GEMINI_API_KEY`.
2. Install dependencies: `poetry install` (see `pyproject.toml`).
3. Run the service: `python -m src.main`.

See `Idea & Arch Files/devsecops_full_project_architecture.md` for the full
architecture, data flow, and integration matrix.
