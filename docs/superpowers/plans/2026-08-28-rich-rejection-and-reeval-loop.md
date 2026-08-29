# Rich Rejection Modal & Re-Evaluate Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rich two-step rejection popup that shows the step artifact and collects a typed rejection reason, then re-runs that step with the feedback up to MAX_RETRIES=3 times before aborting.

**Architecture:** The artifact produced by each step is stored in `GateAuditEntry` and returned from a new GET detail endpoint; the frontend fetches it when "Reject" is clicked and presents it in a scrollable modal alongside a reason textarea before sending the final decision. The `AsyncDevSecOpsSupervisor` wraps each step+gate pair in a retry loop that passes the rejection feedback back into the step function on re-runs.

**Tech Stack:** Python 3.11, FastAPI, asyncio, Pydantic v2, vanilla JS (ES2020), CSS variables (no framework).

## Global Constraints

- Python venv interpreter: `C:/Users/HimanshuGolani/Desktop/Gemini Hackerthon/SentinelForge/.venv/Scripts/python.exe`
- Run tests with: `.venv/Scripts/python.exe -m pytest tests/ -v` — all 32 existing tests must stay green after every task
- All new tests go in `tests/unit/`; no new test files unless specified
- `src/orchestrator/hitl_gate.py` — only `AsyncHITLGateController` and `GateAuditEntry` change; sync path (`HITLGateController`, `ApprovalChannel` subclasses) is untouched
- `src/orchestrator/supervisor.py` — only `AsyncDevSecOpsSupervisor` changes; `DevSecOpsSupervisor` (sync) is untouched
- `src/models/schemas.py` — do not modify; use existing `GateDecision` with `feedback: str | None`
- Frontend files live in `src/web/static/` (JS, CSS) and `src/web/templates/index.html`
- Max retries = `MAX_RETRIES = 3` (already defined in `supervisor.py:36`)
- CSS must use the existing CSS custom properties: `--bg`, `--panel`, `--panel-border`, `--text`, `--muted`, `--accent`, `--success`, `--danger`

---

## File Map

| File | Change |
|------|--------|
| `src/orchestrator/hitl_gate.py` | Add `artifact` field to `GateAuditEntry`; add `artifact` param to `request_gate_approval()`; add `get_gate_detail()` method |
| `src/web/routes.py` | Add `GET /api/pipeline/{pipeline_id}/gate/{step_id}/detail` endpoint |
| `src/orchestrator/supervisor.py` | Change `_request_gate()` to return `GateDecision`; add `artifact` param; add `feedback` param to each step method; add retry loops in `run_pipeline()` |
| `src/web/templates/index.html` | Add `#reject-modal` HTML after existing `#gate-modal` |
| `src/web/static/style.css` | Add styles for `reject-modal-card`, `artifact-scroll`, `reject-textarea`, `btn-secondary` |
| `src/web/static/app.js` | Two-step reject flow: fetch detail → show reject modal → confirm with reason |
| `tests/unit/test_hitl_gate.py` | New async tests for artifact storage and `get_gate_detail()` |
| `tests/unit/test_supervisor.py` | New async tests for retry loop in `AsyncDevSecOpsSupervisor` |

---

## Task 1: Artifact storage in GateAuditEntry + gate detail endpoint

**Files:**
- Modify: `src/orchestrator/hitl_gate.py`
- Modify: `src/web/routes.py`
- Modify: `tests/unit/test_hitl_gate.py`

**Interfaces:**
- Consumes: existing `AsyncHITLGateController`, `GateAuditEntry`, `PipelineSession.gate`
- Produces:
  - `GateAuditEntry.artifact: dict` — stored when gate is requested
  - `AsyncHITLGateController.request_gate_approval(..., artifact: dict | None = None)` — new optional param
  - `AsyncHITLGateController.get_gate_detail(step_id: int) -> dict | None` — returns latest audit entry for a step
  - `GET /api/pipeline/{pipeline_id}/gate/{step_id}/detail` → `{"step_id": int, "gate_name": str, "summary": str, "artifact": dict | None}`

---

- [ ] **Step 1.1: Write the failing tests for artifact storage**

Add these tests at the bottom of `tests/unit/test_hitl_gate.py`:

```python
import asyncio

def _run(coro):
    return asyncio.run(coro)


def test_async_gate_stores_artifact():
    ctrl = AsyncHITLGateController()
    artifact = {"platform": "CloudRun", "savings_usd": 434.0}

    async def _scenario():
        task = asyncio.create_task(
            ctrl.request_gate_approval(2, "Approach", "summary text", artifact=artifact)
        )
        await asyncio.sleep(0)  # let the gate register
        ctrl.submit_decision(2, approved=True)
        return await task

    _run(_scenario())
    detail = ctrl.get_gate_detail(2)
    assert detail is not None
    assert detail["artifact"] == artifact
    assert detail["gate_name"] == "Approach"
    assert detail["summary"] == "summary text"


def test_async_gate_detail_returns_none_for_unknown_step():
    ctrl = AsyncHITLGateController()
    assert ctrl.get_gate_detail(99) is None


def test_async_gate_detail_returns_latest_on_retry():
    ctrl = AsyncHITLGateController()
    first_artifact = {"attempt": 1}
    second_artifact = {"attempt": 2}

    async def _scenario():
        # First gate request
        task1 = asyncio.create_task(
            ctrl.request_gate_approval(2, "Approach", "first", artifact=first_artifact)
        )
        await asyncio.sleep(0)
        ctrl.submit_decision(2, approved=False, feedback="redo it")
        await task1

        # Second gate request (retry)
        task2 = asyncio.create_task(
            ctrl.request_gate_approval(2, "Approach", "second", artifact=second_artifact)
        )
        await asyncio.sleep(0)
        ctrl.submit_decision(2, approved=True)
        await task2

    _run(_scenario())
    detail = ctrl.get_gate_detail(2)
    assert detail["artifact"] == second_artifact  # latest wins
```

Also add `AsyncHITLGateController` to the existing import at the top of `tests/unit/test_hitl_gate.py`:

```python
from src.orchestrator.hitl_gate import (
    ApprovalChannel, AsyncHITLGateController, HITLGateController,
    ScriptedApprovalChannel, TerminalApprovalChannel, WebApprovalChannel,
)
```

- [ ] **Step 1.2: Run new tests — expect failure**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_hitl_gate.py::test_async_gate_stores_artifact tests/unit/test_hitl_gate.py::test_async_gate_detail_returns_none_for_unknown_step tests/unit/test_hitl_gate.py::test_async_gate_detail_returns_latest_on_retry -v
```

Expected: FAILED — `request_gate_approval` doesn't accept `artifact`, `get_gate_detail` doesn't exist.

- [ ] **Step 1.3: Add `artifact` field to `GateAuditEntry` in `src/orchestrator/hitl_gate.py`**

Find the `GateAuditEntry` dataclass (lines 107–124) and add the field:

```python
@dataclass
class GateAuditEntry:
    """Immutable record of every gate decision — kept for compliance audit trail."""

    step_id: int
    gate_name: str
    summary: str
    tools_used: list[str]
    requested_at: float
    decided_at: float | None = None
    approved: bool | None = None
    feedback: str | None = None
    artifact: dict = field(default_factory=dict)

    @property
    def wait_seconds(self) -> float:
        if self.decided_at is None:
            return 0.0
        return round(self.decided_at - self.requested_at, 2)
```

- [ ] **Step 1.4: Add `artifact` param and `get_gate_detail()` to `AsyncHITLGateController`**

Change the `request_gate_approval` signature (around line 145) to accept `artifact`:

```python
async def request_gate_approval(
    self,
    step_id: int,
    step_name: str,
    summary: str,
    tools_used: list[str] | None = None,
    artifact: dict | None = None,
) -> GateDecision:
    tools_used = tools_used or []
    entry = GateAuditEntry(
        step_id=step_id, gate_name=step_name, summary=summary,
        tools_used=tools_used, requested_at=time.time(),
        artifact=artifact or {},
    )
    self.audit_log.append(entry)
    # ... rest of method unchanged
```

Then add the new method at the end of `AsyncHITLGateController` (after `get_audit_log`):

```python
def get_gate_detail(self, step_id: int) -> dict | None:
    """Returns the latest audit entry for a given step_id, or None if not found."""
    for entry in reversed(self.audit_log):
        if entry.step_id == step_id:
            return {
                "step_id": entry.step_id,
                "gate_name": entry.gate_name,
                "summary": entry.summary,
                "artifact": entry.artifact,
            }
    return None
```

- [ ] **Step 1.5: Run new tests — expect pass**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_hitl_gate.py -v
```

Expected: all 10 tests PASS (7 original + 3 new).

- [ ] **Step 1.6: Add detail endpoint to `src/web/routes.py`**

Add this route after the existing `gate_audit_log` route (after line 119):

```python
@router.get("/api/pipeline/{pipeline_id}/gate/{step_id}/detail")
async def gate_detail(pipeline_id: str, step_id: int) -> dict:
    """Returns the artifact and summary for a pending or recently resolved gate."""
    session = state_manager.get_session(pipeline_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown pipeline_id")
    detail = session.gate.get_gate_detail(step_id)
    if not detail:
        raise HTTPException(status_code=404, detail="No gate detail found for this step")
    return detail
```

- [ ] **Step 1.7: Run full test suite — all 32 must still pass**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: 35 tests PASS (32 original + 3 new).

- [ ] **Step 1.8: Commit**

```bash
git add src/orchestrator/hitl_gate.py src/web/routes.py tests/unit/test_hitl_gate.py
git commit -m "feat: store artifact in GateAuditEntry, add gate detail endpoint"
```

---

## Task 2: Change `_request_gate()` to return GateDecision and pass artifact

**Files:**
- Modify: `src/orchestrator/supervisor.py`

**Interfaces:**
- Consumes: `AsyncHITLGateController.request_gate_approval(..., artifact=...)` from Task 1
- Produces: `AsyncDevSecOpsSupervisor._request_gate(step_id, gate_name, summary, artifact=None) -> GateDecision` — callers get the full decision object (Task 3 uses `decision.feedback`)

---

- [ ] **Step 2.1: Change `_request_gate()` in `src/orchestrator/supervisor.py`**

Find the `_request_gate` method (line 261) and replace it:

```python
async def _request_gate(
    self,
    step_id: int,
    gate_name: str,
    summary: str,
    artifact: dict | None = None,
) -> GateDecision:
    decision = await self.gate.request_gate_approval(
        step_id, gate_name, summary, artifact=artifact
    )
    return decision
```

- [ ] **Step 2.2: Update all existing `_request_gate` call sites in `run_pipeline()`**

The current call sites (lines 153–175) use `if not await self._request_gate(...)`. Change each to use the returned `GateDecision` (keeping the same abort behavior for now — retry loops come in Task 3):

```python
# OLD (line 153):
if not await self._request_gate(2, "Approach",
        f"Recommend migrating '{workload.name}' to {plan.target_platform}: {plan.rationale}"):
    return self._abort("Gate 1 (Approach) rejected")

# NEW (same line, no retry yet):
decision = await self._request_gate(
    2, "Approach",
    f"Recommend migrating '{workload.name}' to {plan.target_platform}: {plan.rationale}",
    artifact=plan.model_dump(),
)
if not decision.approved:
    return self._abort("Gate 1 (Approach) rejected")
```

Apply the same transformation for all 5 gate calls:

**Gate 2 (Code Review, step 3):**
```python
decision = await self._request_gate(
    3, "Code Review",
    f"Branch `{diff.branch_name}` changes {len(diff.files_changed)} file(s): {', '.join(diff.files_changed)}",
    artifact=diff.model_dump(),
)
if not decision.approved:
    return self._abort("Gate 2 (Code Review) rejected")
```

**Gate 3 (Cost & Infra, step 4):**
```python
decision = await self._request_gate(
    4, "Cost & Infra",
    f"${plan.monthly_savings_usd:.2f}/mo savings ({plan.savings_pct:.1f}%). Terraform validated: {infra['validation_passed']}",
    artifact={**infra, "savings_usd": plan.monthly_savings_usd, "savings_pct": plan.savings_pct,
               "target_platform": plan.target_platform},
)
if not decision.approved:
    return self._abort("Gate 3 (Cost & Infra) rejected")
```

**Gate 4 (Security Audit, step 5):**
```python
blocked = self.pentest_agent.is_release_blocked(audit_report)
gate_summary = (f"{len(audit_report.findings)} finding(s), overall risk {audit_report.overall_risk}."
                + (" RELEASE BLOCKED by CRITICAL finding." if blocked else ""))
decision = await self._request_gate(
    5, "Security Audit",
    gate_summary,
    artifact={
        "target": audit_report.target,
        "overall_risk": audit_report.overall_risk,
        "findings": [{"title": f.title, "severity": f.severity, "cvss": f.cvss_score}
                     for f in audit_report.findings],
        "release_blocked": blocked,
    },
)
if not decision.approved or blocked:
    return self._abort("Gate 4 (Security Audit) rejected or blocked")
```

**Gate 5 (Final Sign-off, step 6):**
```python
decision = await self._request_gate(
    6, "Final Sign-off",
    f"Ready to deploy to {deployment['url']}",
    artifact=deployment,
)
if not decision.approved:
    return self._abort("Gate 5 (Final Sign-off) rejected")
```

- [ ] **Step 2.3: Run full test suite — all tests must still pass**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: 35 tests PASS.

- [ ] **Step 2.4: Commit**

```bash
git add src/orchestrator/supervisor.py
git commit -m "feat: _request_gate returns GateDecision and passes artifact to audit log"
```

---

## Task 3: Retry loops in AsyncDevSecOpsSupervisor

**Files:**
- Modify: `src/orchestrator/supervisor.py`
- Modify: `tests/unit/test_supervisor.py`

**Interfaces:**
- Consumes: `_request_gate(...) -> GateDecision` from Task 2; `tracker.update_step_status(step_id, StepStatus.IN_PROGRESS, log_msg=...)` to show re-run in UI
- Produces: each step method gains `feedback: str | None = None`; `run_pipeline()` retries rejected steps up to `MAX_RETRIES` times before aborting

---

- [ ] **Step 3.1: Write failing tests for the retry loop**

Add these tests at the bottom of `tests/unit/test_supervisor.py`:

```python
import asyncio as _asyncio

def _run_async(coro):
    return _asyncio.run(coro)


def _make_async_session():
    from src.orchestrator.state_manager import SessionStateManager
    from src.orchestrator.supervisor import PIPELINE_STEPS
    sm = SessionStateManager()
    session = sm.create_session(PIPELINE_STEPS)
    return session


def test_async_supervisor_retries_on_rejection():
    """Rejected gate triggers step re-run with feedback; second attempt approved."""
    session = _make_async_session()
    feedback_seen = []

    async def _scenario():
        from src.orchestrator.supervisor import AsyncDevSecOpsSupervisor
        sup = AsyncDevSecOpsSupervisor(session)

        # Patch _step_propose to record feedback
        original_propose = sup._step_propose
        async def patched_propose(workload, analysis, feedback=None):
            feedback_seen.append(feedback)
            return await original_propose(workload, analysis, feedback=feedback)
        sup._step_propose = patched_propose

        # First gate: reject; second gate: approve all remaining
        call_count = [0]
        original_gate = sup._request_gate
        async def patched_gate(step_id, gate_name, summary, artifact=None):
            call_count[0] += 1
            if step_id == 2 and call_count[0] == 1:
                from src.models.schemas import GateDecision
                return GateDecision(step_id=step_id, approved=False, feedback="use GKE instead")
            from src.models.schemas import GateDecision
            return GateDecision(step_id=step_id, approved=True)
        sup._request_gate = patched_gate

        return await sup.run_pipeline(
            __import__('src.models.schemas', fromlist=['WorkloadSpec']).WorkloadSpec(
                name="test-app", cpu_cores=4, ram_gb=16,
                disk_gb=100, monthly_requests=500_000, is_stateful=False
            )
        )

    result = _run_async(_scenario())
    assert result["status"] == "DEPLOYED"
    # First propose call has None feedback; second has the rejection feedback
    assert None in feedback_seen
    assert "use GKE instead" in feedback_seen


def test_async_supervisor_aborts_after_max_retries():
    """After MAX_RETRIES+1 rejections on the same step, pipeline is ABORTED."""
    session = _make_async_session()

    async def _scenario():
        from src.orchestrator.supervisor import AsyncDevSecOpsSupervisor
        sup = AsyncDevSecOpsSupervisor(session)

        async def always_reject(step_id, gate_name, summary, artifact=None):
            from src.models.schemas import GateDecision
            return GateDecision(step_id=step_id, approved=False, feedback="never good enough")
        sup._request_gate = always_reject

        from src.models.schemas import WorkloadSpec
        return await sup.run_pipeline(
            WorkloadSpec(name="x", cpu_cores=2, ram_gb=8,
                         disk_gb=50, monthly_requests=100_000, is_stateful=False)
        )

    result = _run_async(_scenario())
    assert result["status"] == "ABORTED"
    assert "max retries" in result["reason"].lower()
```

- [ ] **Step 3.2: Run new tests — expect failure**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_supervisor.py::test_async_supervisor_retries_on_rejection tests/unit/test_supervisor.py::test_async_supervisor_aborts_after_max_retries -v
```

Expected: FAILED — step methods have no `feedback` param, no retry loops exist.

- [ ] **Step 3.3: Add `feedback` param to each step method in `AsyncDevSecOpsSupervisor`**

Update `_step_propose` (keep existing body, just add param and use feedback in log):

```python
async def _step_propose(self, workload: WorkloadSpec, analysis: dict, feedback: str | None = None) -> MigrationPlan:
    log_msg = f"Re-evaluating proposal after feedback: {feedback}" if feedback else "Computing migration cost savings..."
    self.tracker.update_step_status(2, StepStatus.IN_PROGRESS, sub_agent="CostScalingAgent",
                                    log_msg=log_msg)
    await asyncio.sleep(0.4)
    baseline = CostEstimate(platform="GCE", monthly_cost_usd=612.0,
                            breakdown={"compute": 480.0, "disk": 132.0})
    target = CostEstimate(platform="CloudRun", monthly_cost_usd=178.0,
                          breakdown={"compute": 150.0, "requests": 28.0})
    savings = baseline.monthly_cost_usd - target.monthly_cost_usd
    rationale = f"Stateless workload with variable traffic fits serverless scale-to-zero."
    if feedback:
        rationale = f"Revised after feedback '{feedback}': {rationale}"
    plan = MigrationPlan(
        baseline=baseline, target=target, target_platform="CloudRun",
        monthly_savings_usd=savings,
        savings_pct=round(savings / baseline.monthly_cost_usd * 100, 1),
        rationale=rationale,
    )
    self.tracker.update_step_status(2, StepStatus.COMPLETED, log_msg="Proposed migration to Cloud Run.")
    return plan
```

Update `_step_codegen` (add `feedback` param):

```python
async def _step_codegen(self, plan: MigrationPlan, feedback: str | None = None) -> CodeDiff:
    log_msg = f"Re-generating code after feedback: {feedback}" if feedback else "Generating migration code..."
    self.tracker.update_step_status(3, StepStatus.IN_PROGRESS, sub_agent="CodeGeneratorAgent",
                                    tool="mcp_server_git.create_branch", log_msg=log_msg)
    await asyncio.sleep(0.4)
    diff = CodeDiff(
        branch_name="feature/cloud-run-migration",
        files_changed=["Dockerfile", "app/healthz.py", "service.yaml"],
        diff_text="+ added /healthz endpoint for Cloud Run readiness probe",
        unit_tests_added=["test_healthz_endpoint"],
    )
    self.tracker.update_step_status(3, StepStatus.COMPLETED, log_msg=f"Committed to {diff.branch_name}.")
    return diff
```

Update `_step_cost_infra` (add `feedback` param):

```python
async def _step_cost_infra(self, plan: MigrationPlan, feedback: str | None = None) -> dict:
    log_msg = f"Re-generating infra after feedback: {feedback}" if feedback else "Rendering Terraform templates..."
    self.tracker.update_step_status(4, StepStatus.IN_PROGRESS, sub_agent="InfraBuilderAgent",
                                    tool="templates/terraform/cloud_run.tf.j2", log_msg=log_msg)
    await asyncio.sleep(0.4)
    self.tracker.update_step_status(4, StepStatus.COMPLETED,
                                    log_msg="Rendered main.tf + cloudbuild.yaml, terraform validate passed.")
    return {"validation_passed": True, "validation_findings": []}
```

Update `_step_test_and_pentest` (add `feedback` param):

```python
async def _step_test_and_pentest(self, diff: CodeDiff, feedback: str | None = None):
    log_msg = f"Re-running security scan after feedback: {feedback}" if feedback else "Running tests..."
    self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, sub_agent="QAAgent",
                                    tool="pytest", log_msg=log_msg)
    await asyncio.sleep(0.3)
    self.tracker.update_step_status(5, StepStatus.IN_PROGRESS,
                                    log_msg="Test failed: missing /healthz route. Self-healing...")
    await asyncio.sleep(0.3)
    self.tracker.update_step_status(5, StepStatus.IN_PROGRESS,
                                    log_msg="Patch applied. Re-running tests... all passed.")
    self.tracker.update_step_status(5, StepStatus.IN_PROGRESS, sub_agent="PentestAgent",
                                    tool="mcp_server_strix.run_strix_dast_scan")
    report = await asyncio.to_thread(self.pentest_agent.run_security_audit, DEMO_STAGING_URL, "medium")
    self.tracker.update_step_status(5, StepStatus.COMPLETED,
                                    log_msg=f"Strix scan: {len(report.findings)} finding(s), risk={report.overall_risk}.")
    return report
```

Update `_step_deploy` (add `feedback` param):

```python
async def _step_deploy(self, infra: dict, feedback: str | None = None) -> dict:
    log_msg = f"Re-attempting deploy after feedback: {feedback}" if feedback else "Triggering Cloud Build..."
    self.tracker.update_step_status(6, StepStatus.IN_PROGRESS, sub_agent="InfraBuilderAgent",
                                    tool="mcp_server_cicd.trigger_cloud_build", log_msg=log_msg)
    await asyncio.sleep(0.4)
    deployment = {"url": "https://demo-app.staging.run.app", "status": "DEPLOYED"}
    self.tracker.update_step_status(6, StepStatus.COMPLETED,
                                    log_msg=f"Deployed to {deployment['url']}.")
    return deployment
```

- [ ] **Step 3.4: Replace `run_pipeline()` with retry loops**

Replace the entire `run_pipeline` method body in `AsyncDevSecOpsSupervisor` with this:

```python
async def run_pipeline(self, workload: WorkloadSpec) -> dict:
    """Runs the Migration/Cost-Optimization demo scenario end-to-end."""
    try:
        analysis = await self._step_analyze(workload)

        # ── Step 2 + Gate 1 ──────────────────────────────────────────────
        plan, feedback = None, None
        for attempt in range(MAX_RETRIES + 1):
            plan = await self._step_propose(workload, analysis, feedback=feedback)
            decision = await self._request_gate(
                2, "Approach",
                f"Recommend migrating '{workload.name}' to {plan.target_platform}: {plan.rationale}",
                artifact=plan.model_dump(),
            )
            if decision.approved:
                break
            feedback = decision.feedback
            if attempt == MAX_RETRIES:
                return self._abort(f"Gate 1 (Approach) rejected after {MAX_RETRIES} retries")
            self.tracker.update_step_status(2, StepStatus.IN_PROGRESS,
                                            log_msg=f"Re-evaluating after rejection: {feedback}")

        # ── Step 3 + Gate 2 ──────────────────────────────────────────────
        diff, feedback = None, None
        for attempt in range(MAX_RETRIES + 1):
            diff = await self._step_codegen(plan, feedback=feedback)
            decision = await self._request_gate(
                3, "Code Review",
                f"Branch `{diff.branch_name}` changes {len(diff.files_changed)} file(s): {', '.join(diff.files_changed)}",
                artifact=diff.model_dump(),
            )
            if decision.approved:
                break
            feedback = decision.feedback
            if attempt == MAX_RETRIES:
                return self._abort(f"Gate 2 (Code Review) rejected after {MAX_RETRIES} retries")
            self.tracker.update_step_status(3, StepStatus.IN_PROGRESS,
                                            log_msg=f"Re-evaluating after rejection: {feedback}")

        # ── Step 4 + Gate 3 ──────────────────────────────────────────────
        infra, feedback = None, None
        for attempt in range(MAX_RETRIES + 1):
            infra = await self._step_cost_infra(plan, feedback=feedback)
            decision = await self._request_gate(
                4, "Cost & Infra",
                f"${plan.monthly_savings_usd:.2f}/mo savings ({plan.savings_pct:.1f}%). "
                f"Terraform validated: {infra['validation_passed']}",
                artifact={**infra, "savings_usd": plan.monthly_savings_usd,
                           "savings_pct": plan.savings_pct, "target_platform": plan.target_platform},
            )
            if decision.approved:
                break
            feedback = decision.feedback
            if attempt == MAX_RETRIES:
                return self._abort(f"Gate 3 (Cost & Infra) rejected after {MAX_RETRIES} retries")
            self.tracker.update_step_status(4, StepStatus.IN_PROGRESS,
                                            log_msg=f"Re-evaluating after rejection: {feedback}")

        # ── Step 5 + Gate 4 ──────────────────────────────────────────────
        audit_report, feedback = None, None
        for attempt in range(MAX_RETRIES + 1):
            audit_report = await self._step_test_and_pentest(diff, feedback=feedback)
            blocked = self.pentest_agent.is_release_blocked(audit_report)
            gate_summary = (
                f"{len(audit_report.findings)} finding(s), overall risk {audit_report.overall_risk}."
                + (" RELEASE BLOCKED by CRITICAL finding." if blocked else "")
            )
            decision = await self._request_gate(
                5, "Security Audit",
                gate_summary,
                artifact={
                    "target": audit_report.target,
                    "overall_risk": audit_report.overall_risk,
                    "findings": [{"title": f.title, "severity": f.severity, "cvss": f.cvss_score}
                                 for f in audit_report.findings],
                    "release_blocked": blocked,
                },
            )
            if blocked:
                return self._abort("Gate 4 (Security Audit) blocked by CRITICAL finding")
            if decision.approved:
                break
            feedback = decision.feedback
            if attempt == MAX_RETRIES:
                return self._abort(f"Gate 4 (Security Audit) rejected after {MAX_RETRIES} retries")
            self.tracker.update_step_status(5, StepStatus.IN_PROGRESS,
                                            log_msg=f"Re-evaluating after rejection: {feedback}")

        # ── Step 6 + Gate 5 ──────────────────────────────────────────────
        deployment, feedback = None, None
        for attempt in range(MAX_RETRIES + 1):
            deployment = await self._step_deploy(infra, feedback=feedback)
            decision = await self._request_gate(
                6, "Final Sign-off",
                f"Ready to deploy to {deployment['url']}",
                artifact=deployment,
            )
            if decision.approved:
                break
            feedback = decision.feedback
            if attempt == MAX_RETRIES:
                return self._abort(f"Gate 5 (Final Sign-off) rejected after {MAX_RETRIES} retries")
            self.tracker.update_step_status(6, StepStatus.IN_PROGRESS,
                                            log_msg=f"Re-evaluating after rejection: {feedback}")

        self.session.result = {
            "status": "DEPLOYED",
            "plan": plan.model_dump(),
            "deployment": deployment,
            "audit": audit_report.model_dump(),
        }
        return self.session.result
    except Exception as exc:  # noqa: BLE001
        self.session.error = str(exc)
        raise
```

- [ ] **Step 3.5: Run all tests — all 37 must pass**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: 37 tests PASS (35 from Tasks 1–2 + 2 new async supervisor tests).

- [ ] **Step 3.6: Commit**

```bash
git add src/orchestrator/supervisor.py tests/unit/test_supervisor.py
git commit -m "feat: async supervisor retry loops — re-run step with feedback on rejection"
```

---

## Task 4: Rich rejection modal in the frontend

**Files:**
- Modify: `src/web/templates/index.html`
- Modify: `src/web/static/style.css`
- Modify: `src/web/static/app.js`

**Interfaces:**
- Consumes: `GET /api/pipeline/{id}/gate/{step_id}/detail` from Task 1; existing `POST .../gate/{step_id}/decision` endpoint
- Produces:
  - "Reject" button → opens rejection modal (no more immediate rejection)
  - Rejection modal: scrollable artifact JSON section + reason textarea + Confirm/Cancel buttons
  - "Cancel" → returns to gate modal
  - "Confirm Reject" → sends `{approved: false, feedback: <reason>}` to decision endpoint

---

- [ ] **Step 4.1: Add rejection modal HTML to `src/web/templates/index.html`**

Insert the `#reject-modal` div after the existing `#gate-modal` div (after line 65, before `<script>`):

```html
  <!-- Rich rejection modal — shown when user clicks Reject in gate modal -->
  <div id="reject-modal" class="modal hidden">
    <div class="modal-card reject-modal-card">
      <h3>Reject Step</h3>
      <p id="reject-gate-title" class="muted"></p>

      <div class="reject-detail-section">
        <h4 class="reject-section-label">Step Output</h4>
        <div id="reject-artifact" class="artifact-scroll"></div>
      </div>

      <div class="reject-reason-section">
        <label for="reject-reason" class="reject-reason-label">
          Rejection reason <span class="required-star">*</span>
        </label>
        <textarea
          id="reject-reason"
          class="reject-textarea"
          rows="3"
          placeholder="Describe what should change — e.g. 'Use GKE instead of Cloud Run', 'Add rate limiting', 'Fix the critical CVE first'..."
        ></textarea>
      </div>

      <div class="modal-actions">
        <button id="reject-cancel-btn" class="btn btn-secondary">Cancel</button>
        <button id="reject-confirm-btn" class="btn btn-danger" disabled>Confirm Reject</button>
      </div>
    </div>
  </div>
```

The full `index.html` between the `</main>` and `<script>` tags should look like:

```html
  <div id="gate-modal" class="modal hidden">
    <div class="modal-card">
      <h3 id="gate-title">Confirmation Required</h3>
      <p id="gate-summary"></p>
      <div class="modal-actions">
        <button id="gate-reject" class="btn btn-danger">Reject</button>
        <button id="gate-approve" class="btn btn-success">Approve &amp; Proceed</button>
      </div>
    </div>
  </div>

  <div id="reject-modal" class="modal hidden">
    <div class="modal-card reject-modal-card">
      <h3>Reject Step</h3>
      <p id="reject-gate-title" class="muted"></p>

      <div class="reject-detail-section">
        <h4 class="reject-section-label">Step Output</h4>
        <div id="reject-artifact" class="artifact-scroll"></div>
      </div>

      <div class="reject-reason-section">
        <label for="reject-reason" class="reject-reason-label">
          Rejection reason <span class="required-star">*</span>
        </label>
        <textarea
          id="reject-reason"
          class="reject-textarea"
          rows="3"
          placeholder="Describe what should change — e.g. 'Use GKE instead of Cloud Run', 'Add rate limiting', 'Fix the critical CVE first'..."
        ></textarea>
      </div>

      <div class="modal-actions">
        <button id="reject-cancel-btn" class="btn btn-secondary">Cancel</button>
        <button id="reject-confirm-btn" class="btn btn-danger" disabled>Confirm Reject</button>
      </div>
    </div>
  </div>

  <script src="/static/app.js"></script>
```

- [ ] **Step 4.2: Add styles to `src/web/static/style.css`**

Append these rules at the end of `style.css`:

```css
/* ── Rich rejection modal ──────────────────────────────────────────────── */

.btn-secondary {
  background: #232b3d;
  color: var(--text);
}
.btn-secondary:hover { background: #2c3650; }

.reject-modal-card {
  width: 560px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.reject-detail-section {
  margin-top: 12px;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.reject-section-label {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--muted);
}

.artifact-scroll {
  overflow-y: auto;
  max-height: 260px;
  background: #0f1524;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 12px;
  font-family: "Consolas", "Courier New", monospace;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text);
  line-height: 1.5;
}

.reject-reason-section {
  margin-top: 16px;
}

.reject-reason-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.required-star {
  color: var(--danger);
  margin-left: 2px;
}

.reject-textarea {
  width: 100%;
  background: #0f1524;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text);
  resize: vertical;
  min-height: 72px;
  font-family: inherit;
}

.reject-textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(91, 124, 250, 0.15);
}

.reject-textarea::placeholder {
  color: var(--muted);
}
```

- [ ] **Step 4.3: Rewrite `src/web/static/app.js` with two-step reject flow**

Replace the full contents of `app.js` with:

```javascript
// SentinelForge live pipeline stepper — SSE client + gate approval UI.
let pipelineId = null;
let eventSource = null;
let pendingGateStepId = null;

const startBtn = document.getElementById("start-btn");
const pipelineIdLabel = document.getElementById("pipeline-id");
const resultBox = document.getElementById("result-box");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");

// Gate modal elements
const gateModal = document.getElementById("gate-modal");
const gateTitle = document.getElementById("gate-title");
const gateSummary = document.getElementById("gate-summary");
const gateApproveBtn = document.getElementById("gate-approve");
const gateRejectBtn = document.getElementById("gate-reject");

// Rejection reason modal elements
const rejectModal = document.getElementById("reject-modal");
const rejectGateTitle = document.getElementById("reject-gate-title");
const rejectArtifact = document.getElementById("reject-artifact");
const rejectReason = document.getElementById("reject-reason");
const rejectConfirmBtn = document.getElementById("reject-confirm-btn");
const rejectCancelBtn = document.getElementById("reject-cancel-btn");

// ── Event listeners ───────────────────────────────────────────────────────────
startBtn.addEventListener("click", startPipeline);
gateApproveBtn.addEventListener("click", () => submitGateDecision(true));
gateRejectBtn.addEventListener("click", openRejectModal);
rejectCancelBtn.addEventListener("click", closeRejectModal);
rejectConfirmBtn.addEventListener("click", confirmReject);
rejectReason.addEventListener("input", () => {
  rejectConfirmBtn.disabled = rejectReason.value.trim().length === 0;
});

// ── Pipeline start ────────────────────────────────────────────────────────────
async function startPipeline() {
  startBtn.disabled = true;
  resultBox.classList.add("hidden");
  const res = await fetch("/api/pipeline/start", { method: "POST" });
  const data = await res.json();
  pipelineId = data.pipeline_id;
  pipelineIdLabel.textContent = `Run: ${pipelineId}`;
  attachEventStream(pipelineId);
}

function attachEventStream(id) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/pipeline/${id}/events`);
  eventSource.onmessage = (evt) => {
    const state = JSON.parse(evt.data);
    renderState(state);
  };
}

// ── State rendering ───────────────────────────────────────────────────────────
function renderState(state) {
  progressFill.style.width = `${state.pipeline_progress_pct}%`;
  progressLabel.textContent = `${state.pipeline_progress_pct}% complete`;

  state.steps.forEach((step) => {
    const li = document.querySelector(`.step[data-step-id="${step.step_id}"]`);
    const statusEl = document.getElementById(`status-${step.step_id}`);
    const agentEl = document.getElementById(`agent-${step.step_id}`);
    const logEl = document.getElementById(`log-${step.step_id}`);

    li.className = `step status-${step.status.toLowerCase()}`;
    statusEl.textContent = step.status.replace(/_/g, " ");
    agentEl.textContent = step.sub_agent ? `${step.sub_agent}` : "";
    logEl.textContent = step.latest_log || "";

    if (step.status === "WAITING_APPROVAL" && pendingGateStepId !== step.step_id) {
      openGateModal(step);
    }
  });

  fetchAndMaybeShowResult();
}

// ── Gate modal (approval) ─────────────────────────────────────────────────────
function openGateModal(step) {
  pendingGateStepId = step.step_id;
  gateTitle.textContent = `Confirm: ${step.name}`;
  gateSummary.textContent = step.latest_log;
  gateModal.classList.remove("hidden");
}

async function submitGateDecision(approved, feedback = null) {
  if (!pendingGateStepId || !pipelineId) return;
  gateModal.classList.add("hidden");
  await fetch(`/api/pipeline/${pipelineId}/gate/${pendingGateStepId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, feedback }),
  });
  pendingGateStepId = null;
}

// ── Rejection reason modal ────────────────────────────────────────────────────
async function openRejectModal() {
  if (!pendingGateStepId || !pipelineId) return;
  gateModal.classList.add("hidden");

  // Fetch the step artifact from the backend
  let detail = null;
  try {
    const res = await fetch(`/api/pipeline/${pipelineId}/gate/${pendingGateStepId}/detail`);
    if (res.ok) {
      detail = await res.json();
    }
  } catch (_) {
    // Fallback: show the summary text already in the modal
  }

  rejectGateTitle.textContent = detail
    ? `Gate: ${detail.gate_name}`
    : gateTitle.textContent;

  rejectArtifact.textContent = detail && detail.artifact && Object.keys(detail.artifact).length
    ? JSON.stringify(detail.artifact, null, 2)
    : (detail && detail.summary) || gateSummary.textContent || "(no artifact details available)";

  // Reset form
  rejectReason.value = "";
  rejectConfirmBtn.disabled = true;
  rejectModal.classList.remove("hidden");
  rejectReason.focus();
}

function closeRejectModal() {
  rejectModal.classList.add("hidden");
  rejectReason.value = "";
  rejectConfirmBtn.disabled = true;
  // Restore the gate modal so the user can reconsider
  gateModal.classList.remove("hidden");
}

async function confirmReject() {
  const reason = rejectReason.value.trim();
  if (!reason) return;
  rejectModal.classList.add("hidden");
  rejectReason.value = "";
  rejectConfirmBtn.disabled = true;
  await submitGateDecision(false, reason);
}

// ── Result polling ────────────────────────────────────────────────────────────
async function fetchAndMaybeShowResult() {
  if (!pipelineId) return;
  const res = await fetch(`/api/pipeline/${pipelineId}/state`);
  const data = await res.json();
  if (data.result || data.error) {
    resultBox.classList.remove("hidden");
    resultBox.textContent = data.error
      ? `ERROR: ${data.error}`
      : JSON.stringify(data.result, null, 2);
    startBtn.disabled = false;
  }
}
```

- [ ] **Step 4.4: Run full test suite — still green**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: 37 tests PASS (no test depends on JS/CSS).

- [ ] **Step 4.5: Start server and manually test the full flow**

```
.venv/Scripts/python.exe run_server.py
```

Open `http://localhost:8080` in a browser.

**Approve path test:**
1. Click "Run Migration/Cost Demo"
2. When gate modal appears, click "Approve & Proceed"
3. Repeat for all 5 gates
4. Verify "DEPLOYED" result appears in the right panel

**Reject + re-evaluate path test:**
1. Click "Run Migration/Cost Demo"
2. When Gate 1 (Approach) modal appears, click "Reject"
3. Verify: gate modal disappears, rejection modal opens
4. Verify: "Step Output" section shows the `MigrationPlan` JSON (platform, costs, savings)
5. Leave the textarea empty — verify "Confirm Reject" button is disabled
6. Type a reason: "Please use GKE instead of Cloud Run"
7. Click "Confirm Reject"
8. Verify: step 2 shows REJECTED then flips back to IN_PROGRESS (re-evaluating)
9. Verify: step 2 completes and a new gate modal appears for Gate 1 again
10. Click "Approve & Proceed" to continue the pipeline to completion

**Cancel path test:**
1. When a gate modal is open, click "Reject"
2. In the rejection modal, click "Cancel"
3. Verify: rejection modal closes, original gate modal reappears
4. Click "Approve & Proceed" to proceed normally

- [ ] **Step 4.6: Commit**

```bash
git add src/web/templates/index.html src/web/static/style.css src/web/static/app.js
git commit -m "feat: two-step rejection modal with scrollable artifact detail and reason textarea"
```

---

## Post-Implementation Self-Review

After completing all 4 tasks, verify:

1. **32 original tests still pass** — run `pytest tests/ -v` and count
2. **5 new tests all pass** — 3 in `test_hitl_gate.py`, 2 in `test_supervisor.py`
3. **Reject flow works end-to-end**:
   - Gate modal opens on WAITING_APPROVAL
   - Clicking Reject shows the rejection modal with real artifact JSON
   - Empty reason keeps Confirm Reject disabled
   - Confirm Reject sends typed feedback to the backend
   - Pipeline re-runs the step, presents the gate again
4. **Approve flow still works** — entire happy path unchanged
5. **MAX_RETRIES exhaustion** — if you reject 4 times in a row, pipeline shows ABORTED in result box
6. **Cancel behavior** — rejection modal Cancel restores the gate modal

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-08-28-rich-rejection-and-reeval-loop.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
