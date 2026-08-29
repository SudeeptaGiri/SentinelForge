# SentinelForge — Agent Integration Guide

> **For teammates:** This document tells you exactly where your code plugs in,
> how to do it in 3 steps, and includes a ready-made AI prompt you can paste
> directly into Claude / Gemini to have it do the integration for you.

---

## What's Already Built (Person 1)

The full pipeline skeleton is live on branch `Feature/HITL`:

```
User clicks "Run" in browser
        │
        ▼
AsyncDevSecOpsSupervisor.run_pipeline()
        │
        ├─► Step 1: analysis_step()       ← stub (Person 3 replaces)
        ├─► [Gate 1 — human approves in browser]
        ├─► Step 2: proposal_step()       ← stub (Person 2 replaces)
        ├─► [Gate 2 — human approves in browser]
        ├─► Step 3: codegen_step()        ← stub (Person 4 replaces)
        ├─► [Gate 3 — human approves in browser]
        ├─► Step 4: infra_step()          ← stub (Person 2 replaces)
        ├─► [Gate 4 — human approves in browser]
        ├─► Step 5: security_step()       ← Person 5 already wired (async path)
        ├─► [Gate 5 — human approves in browser]
        └─► Step 6: deploy_step()         ← stub (Person 2/5 Day-2 stretch)
```

Every gate is real — it blocks the pipeline on an `asyncio.Future` until the
human clicks Approve or Reject in the browser. Rejecting sends your function
the human's feedback text so you can retry with a corrected output.

---

## The Only File You Touch

```
src/orchestrator/steps.py
```

Find your stub function, replace the body with your real agent call.
**Do not edit any other orchestrator file.**

---

## The Contract (Must Follow Exactly)

Every step function has this signature — **do not change it**:

```python
def your_step(ctx: PipelineContext, feedback: str | None) -> YourReturnType:
```

| Argument | What it contains |
|----------|-----------------|
| `ctx.workload` | `WorkloadSpec` — name, cpu, ram, disk, monthly_requests, is_stateful |
| `ctx.get("step_name")` | Output of a previous step (e.g. `ctx.get("proposal")`) |
| `feedback` | Human's rejection text if the gate fired a reject. `None` on first attempt. |

**Return type must be a Pydantic model from `src/models/schemas.py`.**
Do not return a custom class — convert at the boundary.

---

## Pending Integrations

### Person 2 — Cost & Infra Agent

**Status:** 2 stubs to replace — `proposal_step` and `infra_step`

**Step 2 — `proposal_step`** returns a `MigrationPlan`:
```python
# CURRENT STUB in src/orchestrator/steps.py
def proposal_step(ctx: PipelineContext, feedback: str | None) -> MigrationPlan:
    baseline = CostEstimate(platform="GCE", monthly_cost_usd=120.0,
                            breakdown={"vcpu": 90.0, "ram": 30.0})
    target = CostEstimate(platform="CloudRun", monthly_cost_usd=48.0,
                          breakdown={"vcpu": 30.0, "ram": 18.0})
    savings = baseline.monthly_cost_usd - target.monthly_cost_usd
    return MigrationPlan(
        baseline=baseline, target=target, target_platform="CloudRun",
        monthly_savings_usd=savings,
        savings_pct=round(savings / baseline.monthly_cost_usd * 100, 1),
        rationale="Stateless + bursty traffic fits serverless Cloud Run.",
    )
```

Replace with a call to your `cost_agent.estimate_cost()` and your migration
decision matrix. Read `ctx.workload` for the input. If `feedback` is not None,
adjust your `rationale` or switch `target_platform` based on what the human said.

**Step 4 — `infra_step`** returns `InfraArtifacts`:
```python
# CURRENT STUB
def infra_step(ctx: PipelineContext, feedback: str | None) -> InfraArtifacts:
    return InfraArtifacts(
        main_tf='resource "google_cloud_run_v2_service" "app" { name = "app" }',
        service_yaml="apiVersion: serving.knative.dev/v1\nkind: Service",
        cloudbuild_yaml="steps:\n  - name: gcr.io/cloud-builders/docker",
        validation_passed=True, validation_findings=[],
    )
```

Replace with your `infra_agent.render(plan)`. Get the plan from
`ctx.get("proposal")` — that's Person 2's own Step 2 output.

---

### Person 3 — Analysis Agent

**Status:** 1 stub to replace — `analysis_step`

Step 1 has **no gate** — it runs silently and its output feeds the proposal step.

```python
# CURRENT STUB
def analysis_step(ctx: PipelineContext, feedback: str | None) -> dict:
    return {"summary": "Stateless Flask API on a GCE VM, no autoscaling",
            "detected_platform": "GCE"}
```

Replace with your `analysis_agent` logic. Return a plain `dict` with at least:

```python
{
    "detected_platform": "GCE",           # string
    "summary": "...",                      # shown in gate logs
    "files_of_interest": ["app/main.py"]  # list[str]
}
```

If you call Gemini, wrap the SDK call in `try/except` and fall back to the
hardcoded dict — same pattern as `src/orchestrator/gemini_client.py`.

---

### Person 4 — Code Gen & QA / Self-Heal Agent

**Status:** 1 stub to replace — `codegen_step`

```python
# CURRENT STUB
def codegen_step(ctx: PipelineContext, feedback: str | None) -> CodeDiff:
    return CodeDiff(
        branch_name="migrate/cloud-run",
        files_changed=["app/main.py", "Dockerfile"],
        diff_text="+ @app.get('/healthz')\n+ def healthz():\n+     return {'ok': True}",
        unit_tests_added=["tests/test_healthz.py"],
    )
```

Replace with your `code_gen_agent.generate()` call. Important:

- Read `ctx.get("proposal")` to get the `MigrationPlan` as input.
- **Put your self-heal loop inside this function** — run tests, patch on
  failure, re-run, cap at 3 inner retries. The orchestrator's outer retry
  loop handles gate-level rejects, not test failures.
- If `feedback` is not None, the human rejected your last diff. Use the text
  to regenerate (e.g. "add error handling" → add error handling).

---

### Person 5 — Security / Pentest

**Status:** Async web path is already wired via `AsyncDevSecOpsSupervisor`.
Only the **sync/terminal path** (`security_step` stub in `steps.py`) still
returns dummy data.

If you want the terminal demo (`python -m src.main`) to also run your real
scanner, replace the stub:

```python
# CURRENT STUB
def security_step(ctx: PipelineContext, feedback: str | None) -> AuditReport:
    return AuditReport(
        target_url="https://demo-app.staging.run.app",
        vulnerabilities_found=2, critical_count=0,
        findings=["low: missing security header", "low: verbose error page"],
    )
```

**Important:** Convert `SecurityAuditReport` → `AuditReport` at the boundary:

```python
from src.agents.pentest_agent import PentestAgent
from src.models.schemas import AuditReport

def security_step(ctx: PipelineContext, feedback: str | None) -> AuditReport:
    report = PentestAgent().run_security_audit("https://demo-app.staging.internal")
    return AuditReport(
        target_url=report.target,
        vulnerabilities_found=len(report.findings),
        critical_count=sum(1 for f in report.findings if f.severity == "CRITICAL"),
        findings=[f.title for f in report.findings],
    )
```

---

## How to Test After Integrating

### Step 1 — Unit tests (must stay green)
```bash
cd SentinelForge
.venv/Scripts/python.exe -m pytest tests/ -v
```
All 32 tests must pass. If your change breaks a test in
`tests/unit/test_steps.py`, update only that test.

### Step 2 — Quick smoke of your step alone
```python
from src.orchestrator.steps import your_step
from src.models.schemas import PipelineContext, WorkloadSpec

ctx = PipelineContext(workload=WorkloadSpec(
    name="test-app", cpu_cores=2, ram_gb=8,
    disk_gb=50, monthly_requests=100_000, is_stateful=False
))
print(your_step(ctx, None))          # first attempt
print(your_step(ctx, "try again"))   # simulated rejection feedback
```

### Step 3 — Full visual run
```bash
.venv/Scripts/python.exe run_server.py
# open http://localhost:8080
# click "Run Migration/Cost Demo"
# approve each gate as it appears
```

---

## Do Not Touch These Files

| File | Why |
|------|-----|
| `src/orchestrator/hitl_gate.py` | Gate logic, audit log, timeout — Person 1 |
| `src/orchestrator/supervisor.py` | Retry loop, gate wiring — Person 1 |
| `src/orchestrator/state_manager.py` | Run state — Person 1 |
| `src/web/routes.py` | Web API surface — Person 5 |
| `src/models/schemas.py` | Shared contracts — **ask Person 1 before changing** |
| `tests/unit/test_supervisor.py` | Must stay green — Person 1 |

---

## AI Prompts for Auto-Integration

Paste the prompt for your role directly into Claude or Gemini.
It contains everything the AI needs to do the integration for you.

---

### Prompt for Person 2 — Cost & Infra Agent

```
I am working on SentinelForge, an Autonomous AI DevSecOps Agent.
The orchestrator and HITL gate are already built. I need to wire my
cost/infra agents into the pipeline.

THE ONLY FILE I NEED TO EDIT IS: src/orchestrator/steps.py

My agents live in:
  - src/agents/cost_agent.py      (has estimate_cost(workload, platform) -> CostEstimate)
  - src/agents/infra_agent.py     (has render(plan: MigrationPlan) -> InfraArtifacts)
  - templates/terraform/          (Jinja2 templates)

The two stubs to replace are:

1. proposal_step(ctx, feedback) -> MigrationPlan
   - Input: ctx.workload is a WorkloadSpec (name, cpu_cores, ram_gb, disk_gb,
     monthly_requests, is_stateful)
   - If feedback is not None, a human rejected the last proposal — adjust
     target_platform or rationale based on the feedback text
   - Must return: MigrationPlan from src/models/schemas.py

2. infra_step(ctx, feedback) -> InfraArtifacts
   - Input: ctx.get("proposal") returns the MigrationPlan from step 1
   - Must return: InfraArtifacts from src/models/schemas.py with fields:
     main_tf (str), service_yaml (str), cloudbuild_yaml (str),
     validation_passed (bool), validation_findings (list[str])

Rules:
- Do not change any other file
- Do not change the function signatures
- Return types must be Pydantic models from src/models/schemas.py
- After editing, run: .venv/Scripts/python.exe -m pytest tests/ -v
  All 32 tests must still pass

Please read src/orchestrator/steps.py and my agent files, then replace
the two stub bodies with real calls to my agents.
```

---

### Prompt for Person 3 — Analysis Agent

```
I am working on SentinelForge, an Autonomous AI DevSecOps Agent.
The orchestrator and HITL gate are already built. I need to wire my
analysis agent into the pipeline.

THE ONLY FILE I NEED TO EDIT IS: src/orchestrator/steps.py

My agent lives in:
  - src/agents/analysis_agent.py

The stub to replace is:

analysis_step(ctx, feedback) -> dict
  - Input: ctx.workload is a WorkloadSpec (name, cpu_cores, ram_gb, disk_gb,
    monthly_requests, is_stateful)
  - This step has NO gate — it runs silently before the first human checkpoint
  - feedback will always be None (no gate = no rejection)
  - Must return a plain dict with at least:
    {
      "detected_platform": str,      # e.g. "GCE"
      "summary": str,                # human-readable description shown in logs
      "files_of_interest": list[str] # files the analysis found relevant
    }
  - If you call the Gemini API, wrap the call in try/except and fall back to
    a hardcoded dict if the SDK is unavailable — same pattern as
    src/orchestrator/gemini_client.py

Rules:
- Do not change any other file
- Do not change the function signature
- After editing, run: .venv/Scripts/python.exe -m pytest tests/ -v
  All 32 tests must still pass

Please read src/orchestrator/steps.py and src/agents/analysis_agent.py,
then replace the stub body with a real call to my agent.
```

---

### Prompt for Person 4 — Code Gen & QA / Self-Heal Agent

```
I am working on SentinelForge, an Autonomous AI DevSecOps Agent.
The orchestrator and HITL gate are already built. I need to wire my
code generation and QA self-heal agents into the pipeline.

THE ONLY FILE I NEED TO EDIT IS: src/orchestrator/steps.py

My agents live in:
  - src/agents/code_gen_agent.py   (has generate(plan, feedback) -> CodeDiff)
  - src/agents/qa_agent.py         (has run_tests() -> TestResult, apply_patch())

The stub to replace is:

codegen_step(ctx, feedback) -> CodeDiff
  - Input: ctx.get("proposal") returns a MigrationPlan from the previous step
  - If feedback is not None, the human rejected the last diff — use the
    feedback text to change the generation (e.g. "add error handling" means
    regenerate with error handling added)
  - Must return: CodeDiff from src/models/schemas.py with fields:
    branch_name (str), files_changed (list[str]),
    diff_text (str), unit_tests_added (list[str])

IMPORTANT — Self-heal loop goes INSIDE this function:
  The orchestrator handles gate-level retries (max 3 times if human rejects).
  Test-level failures are yours to handle inside codegen_step itself:
    result = qa_agent.run_tests()
    if result.failed:
        apply_patch(result)
        result = qa_agent.run_tests()
  Cap inner retries at 3. Return the CodeDiff after tests pass.

Rules:
- Do not change any other file
- Do not change the function signature
- After editing, run: .venv/Scripts/python.exe -m pytest tests/ -v
  All 32 tests must still pass

Please read src/orchestrator/steps.py and my agent files, then replace
the stub body with real calls to my agents including the self-heal loop.
```

---

### Prompt for Person 5 — Security / Pentest (sync path only)

```
I am working on SentinelForge, an Autonomous AI DevSecOps Agent.
The orchestrator and HITL gate are already built. My PentestAgent is
already wired into the async web UI path. I only need to wire it into
the sync terminal path as well.

THE ONLY FILE I NEED TO EDIT IS: src/orchestrator/steps.py

My agent lives in:
  - src/agents/pentest_agent.py
    PentestAgent().run_security_audit(url, intensity) -> SecurityAuditReport
    (SecurityAuditReport is from src/models/security_models.py)

The stub to replace is:

security_step(ctx, feedback) -> AuditReport
  - The pipeline expects AuditReport from src/models/schemas.py (NOT
    SecurityAuditReport from security_models.py) — I must convert at the
    boundary
  - Target URL to scan: "https://demo-app.staging.internal"
  - Import PentestAgent lazily inside the function to avoid the mcp import
    chain breaking the sync tests:
      from src.agents.pentest_agent import PentestAgent
  - Convert like this:
      report = PentestAgent().run_security_audit("https://demo-app.staging.internal")
      return AuditReport(
          target_url=report.target,
          vulnerabilities_found=len(report.findings),
          critical_count=sum(1 for f in report.findings if f.severity == "CRITICAL"),
          findings=[f.title for f in report.findings],
      )

Rules:
- Do not change any other file
- Do not change the function signature
- The lazy import (inside the function, not at the top) is required —
  mcp is an optional dep and breaks the 32 unit tests if imported at module level
- After editing, run: .venv/Scripts/python.exe -m pytest tests/ -v
  All 32 tests must still pass

Please read src/orchestrator/steps.py and src/agents/pentest_agent.py,
then replace the stub body with the real agent call shown above.
```

---

## Quick Reference — Return Types per Step

| Step | Function | Must Return |
|------|----------|-------------|
| 1 | `analysis_step` | `dict` with `detected_platform`, `summary`, `files_of_interest` |
| 2 | `proposal_step` | `MigrationPlan` |
| 3 | `codegen_step` | `CodeDiff` |
| 4 | `infra_step` | `InfraArtifacts` |
| 5 | `security_step` | `AuditReport` |
| 6 | `deploy_step` | `dict` with `status`, `url` |

All Pydantic models are in `src/models/schemas.py`.

---

## Questions?

Ping Person 1 (Orchestrator lead) for:
- Adding a new field to a shared schema model
- Understanding why a gate fired unexpectedly
- Any change to `supervisor.py`, `hitl_gate.py`, or `state_manager.py`
