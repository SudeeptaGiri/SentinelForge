# Orchestrator & HITL Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic pipeline engine for SentinelForge's Migration/Cost scenario: an ordered list of steps, each guarded by a Human-in-the-Loop (HITL) confirmation gate, that runs solo with stub agents and prints `PIPELINE COMPLETE`.

**Architecture:** A declarative `PipelineStep` list iterated by one loop in `DevSecOpsSupervisor.run_pipeline`. Gates block on a pluggable `ApprovalChannel` (terminal now, web later). On reject, the human's feedback is fed back into the step and it re-runs (bounded). The supervisor calls Gemini only to classify intent and summarize gate artifacts, always with a deterministic fallback. Run state lives in an in-memory `SessionStateManager`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, `google-genai` (optional, guarded import), FastAPI (existing entrypoint).

## Global Constraints

- **Python:** `^3.11` (matches `pyproject.toml`).
- **Imports:** absolute, `from src.<pkg>...` — the repo root is on `sys.path` (`src/` is a package).
- **Tests:** run from the `SentinelForge` repo root inside the project virtualenv. Commands below use `python -m pytest`; if `python`/`pytest` is not on PATH, use `poetry run pytest` or `py -m pytest` equivalently.
- **Branch:** all commits land on `feature/orchestrator-hitl-gate`.
- **Schemas single source of truth:** every data contract is defined once in `src/models/schemas.py`; no duplicate definitions elsewhere.
- **Gemini degrades gracefully:** a Gemini call must NEVER raise into the pipeline — missing key, missing SDK, or API error falls back to a deterministic template.
- **Retry budget:** `MAX_RETRIES = 3`, mirroring `config/agent_config.yaml` → `agents.supervisor.max_retries`.
- **Scenario scope:** Migration/Cost only. Greenfield/Ongoing are out of scope.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/models/schemas.py` | **New.** All shared Pydantic contracts + orchestrator types (`RunStatus`, `GateRequest`, `PipelineStep`, `PipelineContext`). |
| `src/orchestrator/state_manager.py` | Replace stub. `SessionStateManager` — in-memory run state, gate checkpoints, history. |
| `src/orchestrator/hitl_gate.py` | Replace stub. `ApprovalChannel` interface + `TerminalApprovalChannel`, `ScriptedApprovalChannel`, `WebApprovalChannel` (stub) + `HITLGateController`. |
| `src/orchestrator/gemini_client.py` | **New.** `GeminiClient` — `classify_intent`, `summarize_for_gate`, guarded SDK import + template fallback. |
| `src/orchestrator/steps.py` | **New.** Stub `run_fn`s for the 6 steps + `build_default_steps()`. |
| `src/orchestrator/supervisor.py` | Replace stub. `DevSecOpsSupervisor` — `route()` + `run_pipeline()` loop. |
| `src/main.py` | Extend. `run_agent_session()` wiring + `__main__` block. |
| `tests/unit/*`, `tests/integration/*` | Test files (one per component). |

---

### Task 1: Shared schemas & orchestrator types

**Files:**
- Create: `src/models/schemas.py`
- Test: `tests/unit/test_schemas.py`

**Interfaces:**
- Consumes: nothing (foundational).
- Produces:
  - Enums `StepStatus`, `RunStatus` (str enums).
  - Pydantic models `WorkloadSpec`, `CostEstimate`, `MigrationPlan`, `CodeDiff`, `InfraArtifacts`, `AuditReport`, `GateDecision(step_id:int, approved:bool, feedback:str|None=None)`, `GateRequest(step_id:int, gate_name:str, summary:str, tools_used:list[str], artifact:dict)`.
  - Dataclasses `PipelineStep(id:int, name:str, gate_name:str|None, run_fn:Callable[[PipelineContext, str|None], Any])` and `PipelineContext(workload:WorkloadSpec|None, artifacts:dict)` with methods `store(step, artifact)` and `get(name)->Any`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_schemas.py
from src.models.schemas import (
    StepStatus, RunStatus, WorkloadSpec, CostEstimate, MigrationPlan,
    GateDecision, GateRequest, PipelineStep, PipelineContext,
)


def test_gate_decision_feedback_defaults_none():
    d = GateDecision(step_id=1, approved=True)
    assert d.feedback is None


def test_status_enums_have_expected_members():
    assert StepStatus.WAITING_APPROVAL.value == "WAITING_APPROVAL"
    assert RunStatus.REJECTED.value == "REJECTED"


def test_gate_request_defaults_are_independent():
    a = GateRequest(step_id=1, gate_name="G1", summary="s")
    b = GateRequest(step_id=2, gate_name="G2", summary="s")
    a.tools_used.append("x")
    assert b.tools_used == []  # default_factory, not shared mutable


def test_pipeline_context_store_and_get():
    ctx = PipelineContext(workload=None)
    step = PipelineStep(id=1, name="analysis", gate_name=None, run_fn=lambda c, f: {"ok": True})
    ctx.store(step, {"ok": True})
    assert ctx.get("analysis") == {"ok": True}


def test_migration_plan_roundtrips():
    base = CostEstimate(platform="GCE", monthly_cost_usd=100.0, breakdown={"cpu": 60.0})
    tgt = CostEstimate(platform="CloudRun", monthly_cost_usd=40.0, breakdown={"cpu": 25.0})
    plan = MigrationPlan(baseline=base, target=tgt, target_platform="CloudRun",
                         monthly_savings_usd=60.0, savings_pct=60.0, rationale="stateless")
    assert plan.model_dump()["savings_pct"] == 60.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.models.schemas'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/models/schemas.py
"""Shared Pydantic data contracts + orchestrator-internal types.

Single source of truth for objects that flow between every agent, the
supervisor, and the HITL gates. Everyone imports from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class WorkloadSpec(BaseModel):
    name: str
    cpu_cores: float
    ram_gb: float
    disk_gb: float
    monthly_requests: int
    is_stateful: bool


class CostEstimate(BaseModel):
    platform: str  # "GCE" | "GKE" | "CloudRun"
    monthly_cost_usd: float
    breakdown: dict[str, float]


class MigrationPlan(BaseModel):
    baseline: CostEstimate
    target: CostEstimate
    target_platform: str
    monthly_savings_usd: float
    savings_pct: float
    rationale: str


class CodeDiff(BaseModel):
    branch_name: str
    files_changed: list[str]
    diff_text: str
    unit_tests_added: list[str]


class InfraArtifacts(BaseModel):
    main_tf: str
    service_yaml: str
    cloudbuild_yaml: str
    validation_passed: bool
    validation_findings: list[str]


class AuditReport(BaseModel):
    target_url: str
    vulnerabilities_found: int
    critical_count: int
    findings: list[str]


class GateDecision(BaseModel):
    step_id: int
    approved: bool
    feedback: str | None = None


class GateRequest(BaseModel):
    step_id: int
    gate_name: str
    summary: str
    tools_used: list[str] = Field(default_factory=list)
    artifact: dict = Field(default_factory=dict)


@dataclass
class PipelineStep:
    id: int
    name: str
    gate_name: str | None
    run_fn: Callable[["PipelineContext", str | None], Any]


@dataclass
class PipelineContext:
    workload: WorkloadSpec | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    def store(self, step: "PipelineStep", artifact: Any) -> None:
        self.artifacts[step.name] = artifact

    def get(self, name: str) -> Any:
        return self.artifacts.get(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/models/schemas.py tests/unit/test_schemas.py
git commit -m "feat(models): add shared schemas and orchestrator types"
```

---

### Task 2: SessionStateManager

**Files:**
- Modify: `src/orchestrator/state_manager.py` (replace stub)
- Test: `tests/unit/test_state_manager.py`

**Interfaces:**
- Consumes: `RunStatus`, `GateDecision` from `src.models.schemas`; `GateCheckpoint` from `src.models.checkpoints`.
- Produces:
  - `RunState` dataclass: `pipeline_id`, `status:RunStatus`, `current_step_id:int|None`, `history:list[dict]`, `gate_checkpoints:list[GateCheckpoint]`.
  - `SessionStateManager` with: `create_run(pipeline_id)->RunState`, `get(pipeline_id)->RunState`, `set_current(pipeline_id, step_id)`, `set_status(pipeline_id, status)`, `record_gate(pipeline_id, decision, gate_name)`, `record_error(pipeline_id, step_id, error:str)`, `to_dict(pipeline_id)->dict`, `save_checkpoint(session_id, payload:dict)`, `load_checkpoint(session_id)->dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_state_manager.py
from src.models.schemas import RunStatus, GateDecision
from src.orchestrator.state_manager import SessionStateManager


def test_create_run_starts_pending():
    sm = SessionStateManager()
    run = sm.create_run("p1")
    assert run.status == RunStatus.PENDING
    assert sm.get("p1") is run


def test_set_status_and_current():
    sm = SessionStateManager()
    sm.create_run("p1")
    sm.set_current("p1", 3)
    sm.set_status("p1", RunStatus.RUNNING)
    assert sm.get("p1").current_step_id == 3
    assert sm.get("p1").status == RunStatus.RUNNING


def test_record_gate_appends_checkpoint_and_history():
    sm = SessionStateManager()
    sm.create_run("p1")
    sm.record_gate("p1", GateDecision(step_id=2, approved=True), "Gate 1 - Approach")
    run = sm.get("p1")
    assert len(run.gate_checkpoints) == 1
    assert run.gate_checkpoints[0].gate_name == "Gate 1 - Approach"
    assert run.gate_checkpoints[0].approved is True
    assert any(e["event"] == "gate_decision" for e in run.history)


def test_record_error_logged_in_history():
    sm = SessionStateManager()
    sm.create_run("p1")
    sm.record_error("p1", 4, "boom")
    assert any(e["event"] == "error" and e["error"] == "boom" for e in sm.get("p1").history)


def test_to_dict_shape():
    sm = SessionStateManager()
    sm.create_run("p1")
    d = sm.to_dict("p1")
    assert set(d) >= {"pipeline_id", "status", "current_step_id", "history", "gate_checkpoints"}
    assert d["status"] == "PENDING"


def test_checkpoint_roundtrip():
    sm = SessionStateManager()
    sm.save_checkpoint("s1", {"step": 2})
    assert sm.load_checkpoint("s1") == {"step": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_state_manager.py -v`
Expected: FAIL — `ImportError` / `AttributeError` (methods not defined; stub only has `save_checkpoint`/`load_checkpoint` raising `NotImplementedError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/state_manager.py
"""In-memory session state, gate checkpoints, and run history.

Description: Tracks each pipeline run's status, current step, gate decisions,
             and an event history. In-memory for the hackathon demo; the same
             interface can later front Vertex AI Agent Engine persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.models.checkpoints import GateCheckpoint
from src.models.schemas import GateDecision, RunStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunState:
    pipeline_id: str
    status: RunStatus = RunStatus.PENDING
    current_step_id: int | None = None
    history: list[dict] = field(default_factory=list)
    gate_checkpoints: list[GateCheckpoint] = field(default_factory=list)


class SessionStateManager:
    """Persists and retrieves agent session state and checkpoints."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._checkpoints: dict[str, dict] = {}

    def create_run(self, pipeline_id: str) -> RunState:
        run = RunState(pipeline_id=pipeline_id)
        self._runs[pipeline_id] = run
        self._event(run, "run_created")
        return run

    def get(self, pipeline_id: str) -> RunState:
        return self._runs[pipeline_id]

    def set_current(self, pipeline_id: str, step_id: int) -> None:
        run = self._runs[pipeline_id]
        run.current_step_id = step_id
        self._event(run, "step_started", step_id=step_id)

    def set_status(self, pipeline_id: str, status: RunStatus) -> None:
        run = self._runs[pipeline_id]
        run.status = status
        self._event(run, "status_changed", status=status.value)

    def record_gate(self, pipeline_id: str, decision: GateDecision, gate_name: str) -> None:
        run = self._runs[pipeline_id]
        run.gate_checkpoints.append(
            GateCheckpoint(
                gate_name=gate_name,
                session_id=pipeline_id,
                payload={"step_id": decision.step_id, "feedback": decision.feedback},
                approved=decision.approved,
            )
        )
        self._event(run, "gate_decision", gate=gate_name,
                    approved=decision.approved, feedback=decision.feedback)

    def record_error(self, pipeline_id: str, step_id: int, error: str) -> None:
        run = self._runs[pipeline_id]
        self._event(run, "error", step_id=step_id, error=error)

    def to_dict(self, pipeline_id: str) -> dict:
        run = self._runs[pipeline_id]
        return {
            "pipeline_id": run.pipeline_id,
            "status": run.status.value,
            "current_step_id": run.current_step_id,
            "history": run.history,
            "gate_checkpoints": [c.model_dump() for c in run.gate_checkpoints],
        }

    # --- scaffold-compatible checkpoint API ---
    def save_checkpoint(self, session_id: str, payload: dict) -> None:
        self._checkpoints[session_id] = payload

    def load_checkpoint(self, session_id: str) -> dict:
        return self._checkpoints[session_id]

    def _event(self, run: RunState, event: str, **fields) -> None:
        run.history.append({"ts": _now(), "event": event, **fields})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_state_manager.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/state_manager.py tests/unit/test_state_manager.py
git commit -m "feat(orchestrator): in-memory SessionStateManager with checkpoints and history"
```

---

### Task 3: Approval channels & HITL gate controller

**Files:**
- Modify: `src/orchestrator/hitl_gate.py` (replace stub)
- Test: `tests/unit/test_hitl_gate.py`

**Interfaces:**
- Consumes: `GateRequest`, `GateDecision` from `src.models.schemas`; `SessionStateManager` from `src.orchestrator.state_manager`.
- Produces:
  - `ApprovalChannel` (ABC): `request_approval(request:GateRequest)->GateDecision`.
  - `TerminalApprovalChannel()` — reads `input()`; `y`/`yes` → approved; any other non-empty text → rejected with that text as `feedback`.
  - `ScriptedApprovalChannel(decisions:list[GateDecision])` — pops decisions in order; raises `RuntimeError` if exhausted. (Doubles as the test/headless channel.)
  - `WebApprovalChannel()` — Day-2 stub, `request_approval` raises `NotImplementedError`.
  - `HITLGateController(channel:ApprovalChannel, state:SessionStateManager)` with `request_gate_approval(pipeline_id:str, request:GateRequest)->GateDecision` — calls the channel, records the gate on the state manager, returns the decision.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_hitl_gate.py
import builtins

import pytest

from src.models.schemas import GateDecision, GateRequest
from src.orchestrator.hitl_gate import (
    ApprovalChannel, HITLGateController, ScriptedApprovalChannel,
    TerminalApprovalChannel, WebApprovalChannel,
)
from src.orchestrator.state_manager import SessionStateManager


def _req():
    return GateRequest(step_id=2, gate_name="Gate 1 - Approach", summary="do it")


def test_terminal_channel_yes_approves(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "y")
    d = TerminalApprovalChannel().request_approval(_req())
    assert d.approved is True and d.step_id == 2


def test_terminal_channel_text_rejects_with_feedback(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "add a healthz route")
    d = TerminalApprovalChannel().request_approval(_req())
    assert d.approved is False
    assert d.feedback == "add a healthz route"


def test_scripted_channel_pops_in_order():
    ch = ScriptedApprovalChannel([
        GateDecision(step_id=2, approved=False, feedback="fix"),
        GateDecision(step_id=2, approved=True),
    ])
    assert ch.request_approval(_req()).approved is False
    assert ch.request_approval(_req()).approved is True
    with pytest.raises(RuntimeError):
        ch.request_approval(_req())


def test_web_channel_is_stub():
    with pytest.raises(NotImplementedError):
        WebApprovalChannel().request_approval(_req())


def test_controller_records_gate_on_state():
    sm = SessionStateManager()
    sm.create_run("p1")
    ctrl = HITLGateController(ScriptedApprovalChannel([GateDecision(step_id=2, approved=True)]), sm)
    d = ctrl.request_gate_approval("p1", _req())
    assert d.approved is True
    assert sm.get("p1").gate_checkpoints[0].gate_name == "Gate 1 - Approach"


def test_channel_is_abstract():
    assert issubclass(TerminalApprovalChannel, ApprovalChannel)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_hitl_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'ApprovalChannel'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/hitl_gate.py
"""Human-in-the-Loop confirmation gates.

Description: Blocks pipeline progression until a human approves the current
             gate. The approval CHANNEL is pluggable (terminal now, web later);
             the pipeline calls the controller and never changes when the
             channel swaps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from src.models.schemas import GateDecision, GateRequest
from src.orchestrator.state_manager import SessionStateManager


class ApprovalChannel(ABC):
    """Delivers a human approve/reject decision for a gate. Blocking."""

    @abstractmethod
    def request_approval(self, request: GateRequest) -> GateDecision: ...


class TerminalApprovalChannel(ApprovalChannel):
    """Day-1 channel: prints the gate summary and reads a terminal decision."""

    def request_approval(self, request: GateRequest) -> GateDecision:
        print(f"\n=== {request.gate_name} (step {request.step_id}) ===")
        print(request.summary)
        answer = input("Approve? [y/n] or type feedback: ").strip()
        if answer.lower() in ("y", "yes"):
            return GateDecision(step_id=request.step_id, approved=True)
        return GateDecision(step_id=request.step_id, approved=False,
                            feedback=answer or "rejected")


class ScriptedApprovalChannel(ApprovalChannel):
    """Non-interactive channel: returns preset decisions in order.

    Used by tests and headless/demo runs. Raises if asked for more decisions
    than were scripted, to surface mismatched expectations early.
    """

    def __init__(self, decisions: list[GateDecision]) -> None:
        self._queue: deque[GateDecision] = deque(decisions)

    def request_approval(self, request: GateRequest) -> GateDecision:
        if not self._queue:
            raise RuntimeError("ScriptedApprovalChannel exhausted")
        return self._queue.popleft()


class WebApprovalChannel(ApprovalChannel):
    """Day-2 channel (Person 5).

    Design: set run status WAITING_APPROVAL, block on a threading.Event; a
    FastAPI `POST /runs/{id}/gates/{gate}/decision` endpoint sets the decision
    and the event, unblocking the pipeline thread.
    """

    def request_approval(self, request: GateRequest) -> GateDecision:
        raise NotImplementedError("WebApprovalChannel is implemented by Person 5 (Day 2)")


class HITLGateController:
    """Calls the active approval channel and records the gate on state."""

    def __init__(self, channel: ApprovalChannel, state: SessionStateManager) -> None:
        self.channel = channel
        self.state = state

    def request_gate_approval(self, pipeline_id: str, request: GateRequest) -> GateDecision:
        decision = self.channel.request_approval(request)
        self.state.record_gate(pipeline_id, decision, request.gate_name)
        return decision
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_hitl_gate.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/hitl_gate.py tests/unit/test_hitl_gate.py
git commit -m "feat(orchestrator): pluggable approval channels and HITL gate controller"
```

---

### Task 4: GeminiClient (guarded SDK + template fallback)

**Files:**
- Create: `src/orchestrator/gemini_client.py`
- Modify: `pyproject.toml` (add optional `google-genai` dependency)
- Test: `tests/unit/test_gemini_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (uses only stdlib + optional SDK).
- Produces:
  - `GeminiClient(model:str="gemini-2.5-pro", api_key:str|None=None)`.
  - `.enabled -> bool` (True only if an SDK client was constructed).
  - `.classify_intent(user_input:str) -> str` (returns `"migration_cost"` for the demo scope).
  - `.summarize_for_gate(step_name:str, artifact:dict) -> str` (LLM text when enabled; deterministic template otherwise; never raises).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gemini_client.py
from src.orchestrator.gemini_client import GeminiClient


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(api_key=None)
    assert client.enabled is False


def test_classify_intent_is_migration_cost(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiClient(api_key=None).classify_intent("cut my GCE bill") == "migration_cost"


def test_summarize_fallback_is_deterministic_and_mentions_step(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(api_key=None)
    s1 = client.summarize_for_gate("proposal", {"savings_pct": 60})
    s2 = client.summarize_for_gate("proposal", {"savings_pct": 60})
    assert s1 == s2
    assert "proposal" in s1
    assert "60" in s1


def test_summarize_never_raises_on_bad_artifact(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Should not raise even if artifact is empty
    assert isinstance(GeminiClient(api_key=None).summarize_for_gate("deploy", {}), str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_gemini_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.orchestrator.gemini_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/gemini_client.py
"""Supervisor-level Gemini calls with a deterministic fallback.

Description: Wraps the google-genai SDK for two supervisor tasks: classifying
             user intent and summarizing a step artifact for a HITL gate. If no
             API key or SDK is available (or a call fails), falls back to a
             deterministic template so the pipeline never breaks.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, model: str = "gemini-2.5-pro", api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client = None
        if self._api_key:
            try:
                from google import genai  # guarded: optional dependency

                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:  # noqa: BLE001 - degrade, never crash
                logger.warning("Gemini SDK unavailable (%s); using template fallback", exc)

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
            resp = self._client.models.generate_content(model=self._model, contents=prompt)
            return (resp.text or "").strip() or self._template_summary(step_name, artifact)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash
            logger.warning("Gemini call failed (%s); using template fallback", exc)
            return self._template_summary(step_name, artifact)

    @staticmethod
    def _template_summary(step_name: str, artifact: dict) -> str:
        details = ", ".join(f"{k}={v}" for k, v in artifact.items()) or "no details"
        return f"[{step_name}] Review the result before approving: {details}."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_gemini_client.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Add the optional dependency to pyproject**

Modify `pyproject.toml`, `[tool.poetry.dependencies]` block, adding one line after `pydantic = "*"`:

```toml
google-genai = "*"
```

(The import is guarded, so tests pass whether or not the package is installed.)

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/gemini_client.py tests/unit/test_gemini_client.py pyproject.toml
git commit -m "feat(orchestrator): GeminiClient with guarded SDK and template fallback"
```

---

### Task 5: Stub steps & default step list

**Files:**
- Create: `src/orchestrator/steps.py`
- Test: `tests/unit/test_steps.py`

**Interfaces:**
- Consumes: `PipelineContext`, `PipelineStep`, `MigrationPlan`, `CostEstimate`, `CodeDiff`, `InfraArtifacts`, `AuditReport` from `src.models.schemas`.
- Produces:
  - Six `run_fn`s, each `(ctx:PipelineContext, feedback:str|None) -> artifact`: `analysis_step`, `proposal_step`, `codegen_step`, `infra_step`, `security_step`, `deploy_step`.
  - `build_default_steps() -> list[PipelineStep]` — 6 steps; only step 1 (`analysis`) is ungated; steps 2–6 carry gate names `"Gate 1 - Approach"`, `"Gate 2 - Code Review"`, `"Gate 3 - Cost & Infra"`, `"Gate 4 - Security Audit"`, `"Gate 5 - Final Sign-off"`.

> Note: the test/pentest step function is named `security_step` (NOT `test_*`) so pytest does not mis-collect it as a test.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_steps.py
from src.models.schemas import AuditReport, MigrationPlan, PipelineContext
from src.orchestrator.steps import build_default_steps, proposal_step, security_step


def test_default_steps_shape():
    steps = build_default_steps()
    assert [s.id for s in steps] == [1, 2, 3, 4, 5, 6]
    assert steps[0].gate_name is None                      # analysis ungated
    gated = [s.gate_name for s in steps if s.gate_name]
    assert gated == [
        "Gate 1 - Approach", "Gate 2 - Code Review", "Gate 3 - Cost & Infra",
        "Gate 4 - Security Audit", "Gate 5 - Final Sign-off",
    ]


def test_proposal_step_returns_migration_plan_with_savings():
    plan = proposal_step(PipelineContext(workload=None), None)
    assert isinstance(plan, MigrationPlan)
    assert plan.savings_pct > 0


def test_security_step_returns_audit_report():
    report = security_step(PipelineContext(workload=None), None)
    assert isinstance(report, AuditReport)
    assert report.critical_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_steps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.orchestrator.steps'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/steps.py
"""Day-1 stub run_fns for the six pipeline steps + the default step list.

Each run_fn has signature (ctx: PipelineContext, feedback: str | None) -> artifact.
Teammates replace individual stubs with real agents; the signature is the seam.
"""

from __future__ import annotations

from src.models.schemas import (
    AuditReport, CodeDiff, CostEstimate, InfraArtifacts, MigrationPlan,
    PipelineContext, PipelineStep,
)


def analysis_step(ctx: PipelineContext, feedback: str | None) -> dict:
    return {"summary": "Stateless Flask API on a GCE VM, no autoscaling",
            "detected_platform": "GCE"}


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


def codegen_step(ctx: PipelineContext, feedback: str | None) -> CodeDiff:
    return CodeDiff(
        branch_name="migrate/cloud-run",
        files_changed=["app/main.py", "Dockerfile"],
        diff_text="+ @app.get('/healthz')\n+ def healthz():\n+     return {'ok': True}",
        unit_tests_added=["tests/test_healthz.py"],
    )


def infra_step(ctx: PipelineContext, feedback: str | None) -> InfraArtifacts:
    return InfraArtifacts(
        main_tf='resource "google_cloud_run_v2_service" "app" { name = "app" }',
        service_yaml="apiVersion: serving.knative.dev/v1\nkind: Service",
        cloudbuild_yaml="steps:\n  - name: gcr.io/cloud-builders/docker",
        validation_passed=True, validation_findings=[],
    )


def security_step(ctx: PipelineContext, feedback: str | None) -> AuditReport:
    return AuditReport(
        target_url="https://demo-app.staging.run.app",
        vulnerabilities_found=2, critical_count=0,
        findings=["low: missing security header", "low: verbose error page"],
    )


def deploy_step(ctx: PipelineContext, feedback: str | None) -> dict:
    return {"status": "deployed", "url": "https://demo-app.staging.run.app"}


def build_default_steps() -> list[PipelineStep]:
    return [
        PipelineStep(1, "analysis", None, analysis_step),
        PipelineStep(2, "proposal", "Gate 1 - Approach", proposal_step),
        PipelineStep(3, "codegen", "Gate 2 - Code Review", codegen_step),
        PipelineStep(4, "infra", "Gate 3 - Cost & Infra", infra_step),
        PipelineStep(5, "test_pentest", "Gate 4 - Security Audit", security_step),
        PipelineStep(6, "deploy", "Gate 5 - Final Sign-off", deploy_step),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_steps.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/steps.py tests/unit/test_steps.py
git commit -m "feat(orchestrator): stub run_fns and default 6-step pipeline"
```

---

### Task 6: DevSecOpsSupervisor — the run loop

**Files:**
- Modify: `src/orchestrator/supervisor.py` (replace stub)
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Consumes: `RunStatus`, `GateRequest`, `GateDecision`, `PipelineContext`, `PipelineStep`, `WorkloadSpec` from `src.models.schemas`; `SessionStateManager`; `HITLGateController`; `GeminiClient`; `build_default_steps`.
- Produces:
  - `DevSecOpsSupervisor(gate:HITLGateController, state:SessionStateManager, gemini:GeminiClient|None=None, steps:list[PipelineStep]|None=None, max_retries:int=MAX_RETRIES)`.
  - `.run_pipeline(pipeline_id:str, workload:WorkloadSpec) -> RunStatus`.
  - `.route(user_input:str, pipeline_id:str="demo", workload:WorkloadSpec|None=None) -> RunStatus`.
  - Module constant `MAX_RETRIES = 3`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_supervisor.py
from src.models.schemas import GateDecision, PipelineContext, PipelineStep, RunStatus, WorkloadSpec
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import HITLGateController, ScriptedApprovalChannel
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import DevSecOpsSupervisor

WL = WorkloadSpec(name="x", cpu_cores=4, ram_gb=16, disk_gb=100,
                  monthly_requests=500000, is_stateful=False)


def _supervisor(decisions, steps, max_retries=3):
    state = SessionStateManager()
    gate = HITLGateController(ScriptedApprovalChannel(decisions), state)
    sup = DevSecOpsSupervisor(gate=gate, state=state, gemini=GeminiClient(api_key=None),
                              steps=steps, max_retries=max_retries)
    return sup, state


def test_all_approved_completes(capsys):
    steps = [
        PipelineStep(1, "a", None, lambda c, f: {"ok": 1}),
        PipelineStep(2, "b", "Gate 1 - Approach", lambda c, f: {"ok": 2}),
    ]
    sup, state = _supervisor([GateDecision(step_id=2, approved=True)], steps)
    result = sup.run_pipeline("p1", WL)
    assert result == RunStatus.COMPLETED
    assert state.get("p1").status == RunStatus.COMPLETED
    assert "PIPELINE COMPLETE" in capsys.readouterr().out


def test_reject_reruns_step_with_feedback():
    seen: list[str | None] = []

    def gated(ctx, feedback):
        seen.append(feedback)
        return {"attempt": len(seen)}

    steps = [PipelineStep(2, "b", "Gate 1 - Approach", gated)]
    sup, state = _supervisor(
        [GateDecision(step_id=2, approved=False, feedback="add healthz"),
         GateDecision(step_id=2, approved=True)],
        steps,
    )
    result = sup.run_pipeline("p1", WL)
    assert result == RunStatus.COMPLETED
    assert seen == [None, "add healthz"]   # feedback fed back on the re-run


def test_reject_past_budget_rejects():
    steps = [PipelineStep(2, "b", "Gate 1 - Approach", lambda c, f: {"x": 1})]
    sup, state = _supervisor(
        [GateDecision(step_id=2, approved=False, feedback="no"),
         GateDecision(step_id=2, approved=False, feedback="still no")],
        steps, max_retries=1,
    )
    assert sup.run_pipeline("p1", WL) == RunStatus.REJECTED
    assert state.get("p1").status == RunStatus.REJECTED


def test_step_exception_fails_after_budget():
    def boom(ctx, feedback):
        raise ValueError("kaboom")

    steps = [PipelineStep(1, "a", None, boom)]
    sup, state = _supervisor([], steps, max_retries=1)
    assert sup.run_pipeline("p1", WL) == RunStatus.FAILED
    assert any(e["event"] == "error" for e in state.get("p1").history)


def test_route_classifies_then_runs(capsys):
    from src.orchestrator.steps import build_default_steps
    approvals = [GateDecision(step_id=i, approved=True) for i in range(2, 7)]
    state = SessionStateManager()
    gate = HITLGateController(ScriptedApprovalChannel(approvals), state)
    sup = DevSecOpsSupervisor(gate=gate, state=state, gemini=GeminiClient(api_key=None),
                              steps=build_default_steps())
    assert sup.route("cut my cloud bill", pipeline_id="p1", workload=WL) == RunStatus.COMPLETED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_supervisor.py -v`
Expected: FAIL — `ImportError` (`DevSecOpsSupervisor` has no `run_pipeline`; stub only defines `route` raising `NotImplementedError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/supervisor.py
"""Main supervisor: routes intent and runs the gated pipeline loop.

Description: Owns the end-to-end control flow. Iterates a declarative list of
             PipelineSteps; after each gated step it asks Gemini for a summary,
             presents the HITL gate, and on reject re-runs the step with the
             human's feedback (bounded by max_retries).
"""

from __future__ import annotations

import logging

from src.models.schemas import (
    GateRequest, PipelineContext, PipelineStep, RunStatus, WorkloadSpec,
)
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import HITLGateController
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.steps import build_default_steps

logger = logging.getLogger(__name__)

MAX_RETRIES = 3  # mirrors config/agent_config.yaml -> agents.supervisor.max_retries


class DevSecOpsSupervisor:
    """Routes tasks and enforces HITL gates across the pipeline."""

    def __init__(
        self,
        gate: HITLGateController,
        state: SessionStateManager,
        gemini: GeminiClient | None = None,
        steps: list[PipelineStep] | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.gate = gate
        self.state = state
        self.gemini = gemini or GeminiClient()
        self.steps = steps if steps is not None else build_default_steps()
        self.max_retries = max_retries

    def route(self, user_input: str, pipeline_id: str = "demo",
              workload: WorkloadSpec | None = None) -> RunStatus:
        scenario = self.gemini.classify_intent(user_input)
        logger.info("Routed intent %r -> scenario %r", user_input, scenario)
        return self.run_pipeline(pipeline_id, workload or self._demo_workload())

    def run_pipeline(self, pipeline_id: str, workload: WorkloadSpec) -> RunStatus:
        self.state.create_run(pipeline_id)
        ctx = PipelineContext(workload=workload)

        for step in self.steps:
            self.state.set_current(pipeline_id, step.id)
            feedback: str | None = None

            for attempt in range(self.max_retries + 1):
                self.state.set_status(pipeline_id, RunStatus.RUNNING)
                try:
                    artifact = step.run_fn(ctx, feedback)
                except Exception as exc:  # noqa: BLE001 - record and bound-retry
                    self.state.record_error(pipeline_id, step.id, str(exc))
                    if attempt == self.max_retries:
                        self.state.set_status(pipeline_id, RunStatus.FAILED)
                        return RunStatus.FAILED
                    feedback = f"previous attempt raised: {exc}"
                    continue

                ctx.store(step, artifact)
                if step.gate_name is None:
                    break

                payload = self._as_dict(artifact)
                summary = self.gemini.summarize_for_gate(step.name, payload)
                self.state.set_status(pipeline_id, RunStatus.WAITING_APPROVAL)
                request = GateRequest(step_id=step.id, gate_name=step.gate_name,
                                      summary=summary, tools_used=[step.name],
                                      artifact=payload)
                decision = self.gate.request_gate_approval(pipeline_id, request)
                if decision.approved:
                    break
                feedback = decision.feedback
                if attempt == self.max_retries:
                    self.state.set_status(pipeline_id, RunStatus.REJECTED)
                    return RunStatus.REJECTED

        self.state.set_status(pipeline_id, RunStatus.COMPLETED)
        print("PIPELINE COMPLETE")
        return RunStatus.COMPLETED

    @staticmethod
    def _as_dict(artifact) -> dict:
        if hasattr(artifact, "model_dump"):
            return artifact.model_dump()
        if isinstance(artifact, dict):
            return artifact
        return {"value": str(artifact)}

    @staticmethod
    def _demo_workload() -> WorkloadSpec:
        return WorkloadSpec(name="legacy-api", cpu_cores=4, ram_gb=16, disk_gb=100,
                            monthly_requests=500_000, is_stateful=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_supervisor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/supervisor.py tests/unit/test_supervisor.py
git commit -m "feat(orchestrator): supervisor run loop with gated steps and feedback retries"
```

---

### Task 7: Wire main.py entrypoint + integration smoke test

**Files:**
- Modify: `src/main.py`
- Test: `tests/integration/test_pipeline_smoke.py`

**Interfaces:**
- Consumes: `WorkloadSpec`, `RunStatus` from `src.models.schemas`; `SessionStateManager`; `TerminalApprovalChannel`, `HITLGateController`, `ApprovalChannel`; `GeminiClient`; `DevSecOpsSupervisor`.
- Produces:
  - `run_agent_session(channel:ApprovalChannel|None=None, workload:WorkloadSpec|None=None, pipeline_id:str="demo") -> RunStatus`.
  - `__main__` block calling `run_agent_session()` so `python -m src.main` runs the terminal demo.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_pipeline_smoke.py
from src.main import run_agent_session
from src.models.schemas import GateDecision, RunStatus, WorkloadSpec
from src.orchestrator.hitl_gate import ScriptedApprovalChannel

WL = WorkloadSpec(name="legacy", cpu_cores=4, ram_gb=16, disk_gb=100,
                  monthly_requests=500000, is_stateful=False)


def test_full_pipeline_all_approved(capsys):
    approvals = [GateDecision(step_id=i, approved=True) for i in range(2, 7)]  # 5 gates
    status = run_agent_session(channel=ScriptedApprovalChannel(approvals), workload=WL)
    assert status == RunStatus.COMPLETED
    assert "PIPELINE COMPLETE" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_pipeline_smoke.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_agent_session'` returns `NotImplementedError` when called (stub raises).

- [ ] **Step 3: Write minimal implementation**

```python
# src/main.py
"""Service entrypoint (FastAPI / Agent Engine server).

Exposes the health endpoint and wires an agent session to the supervisor.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.models.schemas import RunStatus, WorkloadSpec
from src.orchestrator.gemini_client import GeminiClient
from src.orchestrator.hitl_gate import (
    ApprovalChannel, HITLGateController, TerminalApprovalChannel,
)
from src.orchestrator.state_manager import SessionStateManager
from src.orchestrator.supervisor import DevSecOpsSupervisor

app = FastAPI(title="SentinelForge DevSecOps Agent")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


def run_agent_session(
    channel: ApprovalChannel | None = None,
    workload: WorkloadSpec | None = None,
    pipeline_id: str = "demo",
) -> RunStatus:
    """Start a supervised agent session for the migration/cost demo."""
    state = SessionStateManager()
    gate = HITLGateController(channel or TerminalApprovalChannel(), state)
    supervisor = DevSecOpsSupervisor(gate=gate, state=state, gemini=GeminiClient())
    return supervisor.route(
        "Migrate my legacy GCE app to cut monthly cost",
        pipeline_id=pipeline_id,
        workload=workload,
    )


if __name__ == "__main__":
    run_agent_session()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_pipeline_smoke.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full suite + the terminal demo**

Run: `python -m pytest -v`
Expected: PASS (all unit + integration tests green)

Manual smoke (the Day-1 Definition of Done):
Run: `python -m src.main`
Expected: prints each gate summary, pauses for `Approve? [y/n] or type feedback:` five times; typing `y` five times ends with `PIPELINE COMPLETE`.

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/integration/test_pipeline_smoke.py
git commit -m "feat(main): wire run_agent_session and full-pipeline smoke test"
```

---

## Self-Review

**1. Spec coverage:**
- §2 decision 1 (deterministic + Gemini in supervisor) → Tasks 4, 6. ✅
- §2 decision 2 (pluggable channel, blocking) → Task 3. ✅
- §2 decision 3 (reject re-runs with feedback, bounded) → Task 6 (`test_reject_reruns_step_with_feedback`, `test_reject_past_budget_rejects`). ✅
- §2 decision 4 / §6 (declarative step list + one loop) → Tasks 5, 6. ✅
- §5 data shapes + reconciliation (`GateCheckpoint` kept, controller returns `GateDecision`) → Tasks 1, 2, 3. ✅
- §6 gate mapping (analysis ungated, 5 gates) → Task 5 (`test_default_steps_shape`). ✅
- §7 channels incl. Web stub → Task 3. ✅
- §8 state manager (`to_dict`, checkpoints, history) → Task 2. ✅
- §9 Gemini fallback → Task 4. ✅
- §10 error handling (step raise → retry → FAILED) → Task 6 (`test_step_exception_fails_after_budget`). ✅
- §11 testing (scripted channel, Day-1 DoD) → Tasks 6, 7. ✅
- §12 teammate seam (`run_fn` signature) → Task 5. ✅

**2. Placeholder scan:** No TBD/TODO/"add error handling" — every code step is complete. ✅

**3. Type consistency:** `request_gate_approval(pipeline_id, request)` is defined in Task 3 and called with the same signature in Task 6. `run_fn(ctx, feedback)` is consistent across Tasks 1/5/6. `GateDecision(step_id, approved, feedback)` used identically everywhere. `RunStatus` members match between Tasks 1, 2, 6. ✅
