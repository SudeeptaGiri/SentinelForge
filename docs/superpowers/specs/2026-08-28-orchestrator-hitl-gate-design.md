# Orchestrator & HITL Gate — Design Spec

- **Date:** 2026-08-28
- **Owner:** Person 1 (Orchestrator & HITL Gate Lead)
- **Scenario scope:** Migration / Cost Optimization only (Greenfield & Ongoing are stretch goals)
- **Branch:** `feature/orchestrator-hitl-gate`

## 1. Purpose

Build the pipeline engine every other teammate plugs into: a deterministic control plane
that runs the Migration/Cost scenario as an ordered list of steps, pausing at five
Human-in-the-Loop (HITL) confirmation gates. The orchestrator owns end-to-end control
flow, gate enforcement, run state, and the two Gemini calls made at the supervisor level.

The demo Definition of Done: `python -m src.main` walks all five gates, pausing for a
human decision at each, re-running a step with feedback on reject, and printing
`PIPELINE COMPLETE` on success.

## 2. Decisions (locked)

1. **Deterministic Python skeleton; Gemini used by the supervisor.** Control flow is plain,
   reliable Python. Gemini is called at exactly two points — intent classification and
   gate-summary generation — each with a deterministic fallback so a missing key or offline
   run never breaks the demo.
2. **Pluggable approval channel; pipeline blocks on it.** A `HITLGateController` delegates to
   an `ApprovalChannel` interface. Day 1 uses a terminal channel (`input()`); Person 5 later
   drops in a web channel. The pipeline calls the gate and blocks; its control-flow code never
   changes when the channel swaps. The run executes on a background thread.
3. **Reject re-runs the step with feedback (bounded).** On reject, the human's feedback text is
   fed back into that step's `run_fn` and the step re-runs, up to `MAX_RETRIES` times
   (from `agent_config.yaml`, supervisor tier = 3), then the run halts as `REJECTED`.
4. **Internal structure = declarative step list (Approach A).** The pipeline is a list of
   `PipelineStep` objects iterated by one loop, so the reject-retry-with-feedback logic and the
   Gemini-summary call are each written exactly once.

## 3. Architecture

```
                        DevSecOpsSupervisor.run_pipeline()   [background thread]
                                     │
        ┌────────────────────────────┼─────────────────────────────┐
        │                            │                             │
   step.run_fn(ctx, feedback)   GeminiClient                 HITLGateController
   (teammate agents / stubs)    .classify_intent()           .request_gate_approval()
        │                       .summarize_for_gate()               │
   PipelineContext (artifacts)        │                       ApprovalChannel (interface)
        │                             │                    ┌────────┴─────────┐
        └──────────► SessionStateManager ◄─────────────────┤ Terminal   │ Web │
                     (in-memory dict:                       │ (Day 1)    │(P5) │
                      status, current step,                 └────────────┴─────┘
                      history, gate checkpoints)
```

Gemini calls degrade to deterministic templates when no key is configured.

## 4. Files owned by Person 1

| File | Role | Status |
|------|------|--------|
| `src/models/schemas.py` | Shared Pydantic contracts + orchestrator-internal types. Person 1 is maintainer. | **New** |
| `src/orchestrator/supervisor.py` | `DevSecOpsSupervisor` — `route()` + `run_pipeline()`; owns the step list and the loop. | Replace stub |
| `src/orchestrator/hitl_gate.py` | `ApprovalChannel` interface, `TerminalApprovalChannel`, `WebApprovalChannel` (stub for P5), `HITLGateController`. | Replace stub |
| `src/orchestrator/state_manager.py` | `SessionStateManager` — in-memory run state. | Replace stub |
| `src/orchestrator/gemini_client.py` | `GeminiClient` — `classify_intent()`, `summarize_for_gate()`; SDK-backed, template fallback. | **New** |
| `src/main.py` | Wire `run_agent_session()` (and later a FastAPI trigger) to start a run. | Extend |

## 5. Data shapes (`src/models/schemas.py`)

Team-plan contracts, verbatim (single source of truth; everyone imports from here):

- `StepStatus` (enum): `PENDING`, `WAITING_APPROVAL`, `IN_PROGRESS`, `COMPLETED`, `FAILED`
- `WorkloadSpec`, `CostEstimate`, `MigrationPlan`, `CodeDiff`, `InfraArtifacts`, `AuditReport`
- `GateDecision`: `step_id: int`, `approved: bool`, `feedback: str | None = None`

Orchestrator-internal types (added to the same file):

- `RunStatus` (enum): `PENDING`, `RUNNING`, `WAITING_APPROVAL`, `COMPLETED`, `REJECTED`, `FAILED`
- `PipelineContext`: accumulates each step's artifact (analysis result, migration plan, code diff,
  infra artifacts, audit report, deploy result) and the original `WorkloadSpec`.
- `GateRequest`: `step_id: int`, `gate_name: str`, `summary: str`, `tools_used: list[str]`,
  `artifact: dict` — the payload shown to the human at a gate.
- `PipelineStep`: `id: int`, `name: str`, `gate_name: str | None`, `run_fn: Callable`.

**Reconciliation with existing scaffold:**
- Keep `src/models/checkpoints.py::GateCheckpoint`; `SessionStateManager` writes one per gate.
- The scaffold's `HITLGateController.request_gate_approval(gate_name, payload) -> bool` becomes
  `request_gate_approval(request: GateRequest) -> GateDecision`.
- The scaffold's `DevSecOpsSupervisor.route(user_input) -> None` stays as the public entry point
  and internally classifies intent, then calls `run_pipeline(...)`.

## 6. The step list and the loop

Ordered steps (maps to the team plan's control flow). Analysis has no gate; it feeds Proposal.

| # | Step | Gate | Produces |
|---|------|------|----------|
| 1 | Analysis | — | analysis summary / detected platform |
| 2 | Proposal | **Gate 1 — Approach** | `MigrationPlan` |
| 3 | CodeGen | **Gate 2 — Code Review** | `CodeDiff` |
| 4 | Cost / Infra | **Gate 3 — Cost & Infra** | `InfraArtifacts` |
| 5 | Test + Pentest | **Gate 4 — Security Audit** | `AuditReport` + test result |
| 6 | Deploy | **Gate 5 — Final Sign-off** | deploy result (mocked URL) |

Loop (single place for retry-with-feedback):

```python
for step in steps:
    state.set_current(step.id)
    feedback = None
    for attempt in range(MAX_RETRIES + 1):
        state.set_status(RunStatus.RUNNING)
        try:
            artifact = step.run_fn(context, feedback)
        except Exception as exc:
            state.record_error(step, exc)
            if attempt == MAX_RETRIES:
                state.set_status(RunStatus.FAILED); return
            feedback = f"previous attempt raised: {exc}"; continue
        context.store(step, artifact)
        if step.gate_name is None:
            break
        summary  = gemini.summarize_for_gate(step, artifact)   # template fallback
        request  = GateRequest(step.id, step.gate_name, summary, tools_used(step), artifact)
        decision = gate.request_gate_approval(request)          # BLOCKS
        state.record_gate(step, decision)
        if decision.approved:
            break
        feedback = decision.feedback
        if attempt == MAX_RETRIES:
            state.set_status(RunStatus.REJECTED); return
state.set_status(RunStatus.COMPLETED)
print("PIPELINE COMPLETE")
```

## 7. HITL gate & approval channel

- `ApprovalChannel` (abstract): `request_approval(request: GateRequest) -> GateDecision`, blocking.
- `TerminalApprovalChannel`: prints the gate summary, reads `input("Approve? [y/n] or type feedback: ")`.
  `y`/`yes` → approved. Any other non-empty text → rejected, with that text as `feedback`.
- `WebApprovalChannel` (Person 5, Day 2): sets run status `WAITING_APPROVAL`, blocks on a
  `threading.Event`; a FastAPI `POST /runs/{id}/gates/{gate}/decision` sets the decision and the
  event, unblocking the pipeline thread. **Delivered as a documented stub in Day 1 so the seam exists.**
- `HITLGateController`: holds the active channel, calls it, and writes a `GateCheckpoint` to
  `SessionStateManager`. Preserves the scaffold class name and the checkpoint model.

## 8. State manager

In-memory `dict[pipeline_id] -> RunState`. `RunState` holds: `status: RunStatus`,
`current_step_id: int`, `history: list[dict]` (timestamped events), `gate_checkpoints:
list[GateCheckpoint]`, and a `context` snapshot. Methods: `create_run`, `get`, `set_current`,
`set_status`, `record_gate`, `record_error`, `to_dict` (for the UI / `GET /runs/{id}`). The
scaffold's `save_checkpoint` / `load_checkpoint` map onto this.

**Day-2 stretch:** swap the dict for Vertex AI Agent Engine persistence behind the same
interface — no caller changes.

## 9. Gemini in the supervisor (`gemini_client.py`)

`GeminiClient` wraps the `google-genai` SDK; model = supervisor tier (`gemini-2.5-pro`) read
from `config/agent_config.yaml`.

- `classify_intent(user_input: str) -> str`: returns a scenario key. Hard-scoped to
  `"migration_cost"` for the demo (still calls Gemini to demonstrate intent routing).
- `summarize_for_gate(step_name: str, artifact: dict) -> str`: turns a raw artifact into a crisp,
  human-readable gate summary.
- **Fallbacks:** if no API key / SDK error / offline → return a deterministic template summary and
  log a warning. Never raises into the pipeline.
- **SDK over CLI:** in-process, no subprocess parsing, trivially mockable. A `gemini` CLI path is
  kept as an optional fallback behind the same method signatures.

## 10. Error handling

- Step raises → caught, recorded in history, retried within the step's budget, then clean
  `FAILED` abort with the error surfaced.
- Gemini unavailable → template fallback + warning; pipeline continues.
- Reject past `MAX_RETRIES` → `REJECTED` halt with a clear "halted at Gate N" message.
- Background-thread exceptions → captured into `RunState` so the terminal/UI shows them; no
  silent hang.

## 11. Testing

- **Unit:** drive `run_pipeline` with **fake steps** + a **scripted `ApprovalChannel`** (a queued
  sequence of approve / reject+feedback decisions). Assert: advance-on-approve, re-run-on-reject
  passes feedback into `run_fn`, abort-after-budget, correct `history` and `gate_checkpoints`.
  Gemini is mocked; no real `input()`, no real agents.
- **Integration (Day-1 DoD):** `python -m src.main` runs all six steps with stub `run_fn`s, pauses
  at all five gates via the terminal channel, and prints `PIPELINE COMPLETE`.

## 12. Teammate seams

- **Agents (Persons 2/3/4/5):** each provides a `run_fn(context: PipelineContext, feedback:
  str | None) -> artifact`. Day 1 ships stub `run_fn`s for all six steps so the pipeline runs
  solo; swapping a stub for a real agent is a one-line change in the step list.
- **UI (Person 5):** implements `WebApprovalChannel` and reads `SessionStateManager.to_dict()` for
  the stepper display.

## 13. Out of scope (this spec)

- Real agent logic (owned by Persons 2–5).
- Real MCP servers (architectural nicety; direct function calls are acceptable for the demo).
- Real GCP deploy (mocked "Deployed to https://demo-app.staging.run.app").
- Greenfield / Ongoing scenarios.
