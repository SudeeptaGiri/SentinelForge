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
2. Install dependencies: `poetry install` (see `pyproject.toml`), or with `uv`:
   `uv venv .venv && uv pip install --python .venv fastapi uvicorn pydantic jinja2 pyyaml`.
3. Run the service: `python -m src.main` (serves on `http://localhost:8080`).
4. Open `http://localhost:8080/` for the live pipeline stepper UI. Click
   **Run Migration/Cost Demo** to start the Migration/Cost-Optimization demo
   scenario; approve/reject each of the 5 HITL gates as they appear.

See `Idea & Arch Files/devsecops_full_project_architecture.md` for the full
architecture, data flow, and integration matrix, and
`Idea & Arch Files/team_hackathon_plan.md` for the team build plan and
per-person task breakdown.

## Web Demo UI & Integration Layer (Person 5)

- `src/web/routes.py` — FastAPI routes: serves the stepper page, starts a
  pipeline run as a background task, streams live progress over
  Server-Sent-Events (`/api/pipeline/{id}/events`), and resolves gate
  approvals from the Approve/Reject buttons
  (`POST /api/pipeline/{id}/gate/{step_id}/decision`).
- `src/web/templates/index.html`, `src/web/static/` — the stepper UI (dark
  theme), matching the design in
  `Idea & Arch Files/ui_progress_tracker_and_gates.md`.
- `src/orchestrator/progress_tracker.py` — in-memory step state + SSE fan-out,
  used by both the orchestrator and the UI.
- `src/orchestrator/hitl_gate.py` — async `HITLGateController`; the
  orchestrator `await`s `request_gate_approval(...)` and the web route (or a
  CLI fallback) resolves it via `submit_decision(...)`.
- `src/agents/pentest_agent.py` + `src/mcp_servers/server_strix.py` — the
  Security/Pentest agent. Enforces `config/security_rules.yaml` (host
  allowlist, DAST intensity ceiling) and returns deterministic, realistic
  mock CVSS findings so the demo is reproducible; a real Strix CLI can be
  dropped in behind `run_strix_dast_scan(...)` without touching the agent.
- `src/orchestrator/supervisor.py` — wires the full 6-step / 5-gate demo
  pipeline together. Steps not yet owned by a teammate are clearly marked
  `# MOCK: replace with ...` so real agent logic can be swapped in
  incrementally without breaking the pipeline.
