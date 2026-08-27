# Team Hackathon Plan: Autonomous AI DevSecOps Agent (2-Day Build)

## How to Use This Document

Each of the 5 team members reads only their own section in detail (Section 3), but everyone must read Section 1 and Section 2 together before writing any code. This plan builds the project described in [devsecops_full_project_architecture.md](devsecops_full_project_architecture.md), following the build order in [.github/skills/devsecops-agent-scaffold/SKILL.md](.github/skills/devsecops-agent-scaffold/SKILL.md).

---

## 1. Golden Rules (read as a team, 15 minutes, before Hour 0)

1. **One demo scenario, not three.** Build **Migration/Cost Optimization** end-to-end (already fully spec'd in [cost_migration_build_roadmap.md](cost_migration_build_roadmap.md)). Greenfield/Ongoing scenarios are stretch goals only — do not start them until the core scenario fully works.
2. **Agree on shared data shapes before writing agent logic.** Nobody changes the schemas below mid-hackathon without a 2-minute team shout-out.
3. **Mock your dependencies, don't wait for them.** If your code needs another teammate's piece, write a fake/stub version of it first so you're never blocked.
4. **Integrate every 3-4 hours**, not once at the end. Merge to `main` at every checkpoint in Section 4/5.
5. **Freeze new features for the last 3 hours of Day 2.** Only bug fixes and demo rehearsal after that point.

---

## 2. Shared Contracts (Define Together at Hour 0 — 30 min)

Create `src/models/` first, together, on a shared screen. These are the objects that flow between every person's code:

```python
# src/models/schemas.py
from enum import Enum
from pydantic import BaseModel

class StepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class WorkloadSpec(BaseModel):
    name: str
    cpu_cores: float
    ram_gb: float
    disk_gb: float
    monthly_requests: int
    is_stateful: bool

class CostEstimate(BaseModel):
    platform: str            # "GCE" | "GKE" | "CloudRun"
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
```

**Everyone imports from this one file. No duplicate/competing schema definitions.**

---

## 3. Team Roles — Detailed Task Breakdown

### 👤 Person 1 — Orchestrator & HITL Gate Lead

**Goal:** Build the pipeline engine that every other piece plugs into. This is the critical path — start immediately, work mostly solo for the first 3 hours.

**Owns:** `src/orchestrator/supervisor.py`, `src/orchestrator/state_manager.py`, `src/orchestrator/hitl_gate.py`, `src/models/schemas.py` (maintainer).

**How to achieve it, step by step:**

1. (Hour 0-1) Write `hitl_gate.py` with ONE function: `request_gate_approval(step_id, step_name, summary, tools_used) -> GateDecision`. For Day 1, this can literally be a terminal `input("Approve? [y/n]: ")` — don't build a UI yet, that's Person 5's job later.
2. (Hour 1-2) Write `supervisor.py` as a plain function `run_pipeline(scenario_type, workload_spec)` that calls, in order: analysis → propose → gate1 → codegen → gate2 → cost/infra → gate3 → test/pentest → gate4 → deploy → gate5. At this point every step is a **stub returning fake data** — you're building the skeleton, not the content.
3. (Hour 2-3) Write `state_manager.py`: a simple in-memory dict keyed by `pipeline_id` storing the current step and history (don't over-engineer with a real database — a Python dict is fine for a 2-day hackathon demo).
4. (Hour 3+) Once teammates' real agents are ready, swap each stub call for the real function call, one at a time, testing after each swap.
5. **Definition of done:** Running `python -m src.main` walks through all 5 gates in the terminal with fake data, pausing for `y/n` at each, and prints "PIPELINE COMPLETE" at the end.

**Tools:** Python, pydantic. No GCP credentials needed for this role until Day 2 integration.

---

### 👤 Person 2 — Cost & Infra Agent Lead

**Goal:** Produce the numbers and files that make the demo compelling — the cost savings % and the generated Terraform.

**Owns:** `src/agents/cost_agent.py`, `src/agents/infra_agent.py`, `templates/terraform/*.tf.j2`, `templates/cicd/cloudbuild.yaml.j2`.

**How to achieve it, step by step:**

1. (Hour 0-2) Write `cost_analyzer`-style logic: a function `estimate_cost(workload: WorkloadSpec, platform: str) -> CostEstimate`. Use simple hardcoded per-unit rates for Day 1 (e.g., $0.03/vCPU-hour, $0.004/GB-RAM-hour) — real Cloud Billing API integration is a Day 2 stretch goal, not a Day 1 requirement.
2. (Hour 2-4) Write the decision matrix in `migration_suggester`-style logic: if `is_stateful == False` and `monthly_requests` fits serverless pattern → recommend Cloud Run; if stateful/mesh → GKE Autopilot; else → right-sized GCE. Output a `MigrationPlan`.
3. (Hour 4-6) Write 2 Jinja2 templates: `cloud_run.tf.j2` (parameterize project, region, image, cpu, memory, min/max instances) and `cloudbuild.yaml.j2` (build → scan → push → deploy steps). Use the example in [cost_migration_build_roadmap.md](cost_migration_build_roadmap.md) Section 3 as your starting HCL.
4. (Hour 6-7) Write `infra_agent.py`: takes a `MigrationPlan`, picks the right template, fills parameters, returns `InfraArtifacts`.
5. (Hour 7-8) Add validation: shell out to `terraform validate` if Terraform CLI is installed; if not, at minimum do a basic string/syntax sanity check for the demo.
6. **Definition of done:** Given a sample `WorkloadSpec` (e.g., "old GCE VM, 4 vCPU, 16GB RAM, 500k req/month"), your code prints a `MigrationPlan` with a specific % savings number and a valid-looking `main.tf`.

**Tools:** Python, Jinja2, Terraform CLI (optional but recommended for real `terraform validate`).

---

### 👤 Person 3 — Analysis & Spec Agent Lead

**Goal:** Feed the pipeline's first step — read a codebase or an idea and turn it into something the Proposal step can use.

**Owns:** `src/agents/analysis_agent.py`, `src/agents/spec_agent.py`.

**How to achieve it, step by step:**

1. (Hour 0-1) Sync with Person 1 on exactly what "AnalysisResult" needs to contain (add it to `schemas.py` together if missing — e.g., `detected_platform: str`, `summary: str`, `files_of_interest: list[str]`).
2. (Hour 1-4) Build `analysis_agent.py`: for the demo, this can walk a sample legacy app folder (you can write a small fake "legacy app" — a Flask app with a `Dockerfile` and a GCE deploy script) and produce a summary ("Stateless Flask API, currently on GCE VM, no autoscaling"). Full Graphify/GraphRAG integration is a stretch goal — a simple file-walk + basic heuristics is enough for Day 1.
3. (Hour 4-6) If time allows, call an LLM (Gemini API) to turn the raw file summary into a natural-language description — this is where "AI" visibly shows up in this step for the demo.
4. (Hour 6-8) Build `spec_agent.py` only if the team decides to attempt the Greenfield stretch scenario — otherwise use this time to help Person 2 or Person 4.
5. **Definition of done:** Given a path to the sample legacy app folder, your code returns a short structured summary object usable as input to Person 2's cost/migration logic.

**Tools:** Python, Gemini API key (`google-generativeai` or `google-genai` SDK) for the optional LLM summarization step.

---

### 👤 Person 4 — Code Gen & QA/Self-Heal Agent Lead

**Goal:** Show the pipeline actually writing code and testing it — including one visible self-healing fix, which is a strong demo moment.

**Owns:** `src/agents/code_gen_agent.py`, `src/agents/qa_agent.py`.

**How to achieve it, step by step:**

1. (Hour 0-2) Write `code_gen_agent.py`: given an approved `MigrationPlan`/proposal, generate a small concrete code change (e.g., add a `Dockerfile` + `service.yaml` reference, or a health-check endpoint `/healthz` the Cloud Run probe needs). Output a `CodeDiff` with the actual diff text.
2. (Hour 2-3) Wire basic git operations: create a branch, commit the change, produce `git diff` output as a string (use `subprocess` + `git` CLI, or `GitPython`).
3. (Hour 3-6) Write `qa_agent.py`: run a small pytest suite against the sample app. **On purpose, seed one test that fails initially** (e.g., missing `/healthz` route), so your self-heal loop has something real to fix live.
4. (Hour 6-8) Build the self-heal loop: on test failure, apply a pre-written fix (for the demo, this can be a deterministic fix rather than a full LLM-generated one, to guarantee it works live) — cap retries at 3, matching [implementation_guide_layers.md](implementation_guide_layers.md) guidance.
5. **Definition of done:** Running your test loop shows: test fails → "self-healing..." message → patch applied → test re-run → passes. This should be reliably reproducible for the live demo (don't leave this to chance/randomness).

**Tools:** Python, pytest, git CLI or GitPython.

---

### 👤 Person 5 — Security/Pentest + MCP + UI/Integration Lead

**Goal:** Be the glue — make sure everyone's pieces actually connect, and make the demo look good visually.

**Owns:** `src/agents/pentest_agent.py`, `src/mcp_servers/*` (as needed), the UI/approval front-end, final integration.

**How to achieve it, step by step:**

1. (Hour 0-2) Build `pentest_agent.py` as a **mocked scanner** for Day 1: given a URL, return a fake but realistic `AuditReport` (e.g., "0 critical, 2 low"). Real Strix integration only if time allows on Day 2 — do not block the demo on external tool access.
2. (Hour 2-5) Build a minimal UI: a simple web page (Flask/FastAPI + plain HTML, or even a well-formatted terminal UI) that shows the 6-step stepper from [ui_progress_tracker_and_gates.md](ui_progress_tracker_and_gates.md) with real "Approve / Reject" buttons calling Person 1's `hitl_gate.py`. This replaces the `input()` prompt from Day 1.
3. (Hour 5-8, Day 1 end) Sit with Person 1 and do the **first full integration pass**: plug in Person 2, 3, 4's real code where stubs currently are. Expect and budget time for breakage.
4. (Day 2, ongoing) Own the MCP server wrapping ONLY if the team has time to do the "real" MCP layer — for a 2-day hackathon, it is acceptable to skip MCP entirely and call functions directly; MCP is an architectural nicety, not a demo requirement. Prioritize a working demo over protocol purity.
5. (Day 2, last 4 hours) Own the demo rehearsal: run the full flow twice end-to-end, time it, prepare a fallback recorded video/screenshots in case of live failure.
6. **Definition of done:** A single script/button click runs the entire pipeline from Person 3's analysis through Person 2's cost/infra, Person 4's code/test, your pentest mock, ending in a "deployed" message — with visible approval clicks at each gate.

**Tools:** Flask/FastAPI + HTML/JS (or Streamlit for speed), git.

---

## 4. Day 1 Timeline (Foundation + Parallel Build)

| Time                   | Activity                                                                                                                                   |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Hour 0–0.5             | Whole team: read this plan, agree on schemas (Section 2), confirm demo scenario = Migration/Cost.                                          |
| Hour 0.5–3             | Person 1 builds orchestrator skeleton (visible to all). Persons 2-5 start their own pieces against mocks.                                  |
| Hour 3–6               | Continue parallel build. Person 1 becomes available to help others once skeleton runs.                                                     |
| Hour 6                 | **Checkpoint 1**: everyone pushes to `main`. Person 5 attempts first wiring of Person 2's real cost/infra output into Person 1's pipeline. |
| Hour 6–9               | Fix integration issues. Persons 3 & 4 continue building their pieces.                                                                      |
| Hour 9–12              | Wire in Person 3 (analysis) and Person 4 (codegen/QA) outputs.                                                                             |
| Hour 12 (end of Day 1) | **Checkpoint 2 — target: full pipeline runs end-to-end with a mix of real + mocked pieces**, all 5 gates pausing correctly.                |

## 5. Day 2 Timeline (Real Logic + Polish + Demo Prep)

| Time       | Activity                                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------- |
| Hour 12–16 | Replace remaining mocks with real logic (real Terraform validate, real self-heal fix, real UI instead of terminal). |
| Hour 16    | **Checkpoint 3**: full pipeline, real logic, UI-based approvals working.                                            |
| Hour 16–19 | Bug fixing only. No new features past this point.                                                                   |
| Hour 19–21 | Full demo rehearsal x2. Time it. Identify and fix anything that breaks. Prepare fallback screenshots/video.         |
| Hour 21–22 | Final rehearsal, prepare the pitch narrative (see Section 6).                                                       |
| Hour 22+   | Buffer / rest before presenting.                                                                                    |

---

## 6. Demo Script (What to Show, in Order)

1. "Here's a legacy app currently running on a GCE VM" — show Person 3's analysis output.
2. "The agent proposes migrating to Cloud Run with X% monthly savings" — show Person 2's `MigrationPlan` + cost numbers. **Click Approve (Gate 1).**
3. "It generates the code changes needed" — show Person 4's `CodeDiff`. **Click Approve (Gate 2).**
4. "It generates and validates real Terraform" — show Person 2's `main.tf` + validation passing. **Click Approve (Gate 3).**
5. "It runs tests — watch it self-heal a failure live" — show Person 4's self-heal loop. Then security scan passes. **Click Approve (Gate 4).**
6. "Final deployment sign-off" — **Click Approve (Gate 5).** Show "Deployed" message.
7. Close with the architecture diagram (from [hld_devsecops_agent_architecture.md](hld_devsecops_agent_architecture.md)) to show this scales to 2 more scenarios (Greenfield, Ongoing) beyond what you demoed.

---

## 7. Risk & Fallback Plan

| Risk                                   | Fallback                                                                                                                                                                                                     |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| No real GCP credentials / quota issues | Mock the deploy step with a convincing "Deployed to https://demo-app.staging.run.app" print/UI message — judges care about the orchestration logic, not a real live URL.                                     |
| Strix/Graphify not actually accessible | Use realistic mocked outputs for these agents — be honest about this if asked, focus the pitch on the orchestration + HITL governance pattern, which is real.                                                |
| Self-heal loop is flaky live           | Make the seeded failing test deterministic (not random), so the fix always reproduces the same way in front of judges.                                                                                       |
| Integration breaks late on Day 2       | This is why Checkpoints 1-3 exist — if you're not at "full pipeline runs" by Hour 16, cut a scenario step's polish, not the pipeline's completeness. A fully working simple demo beats a broken complex one. |
| A teammate gets stuck/blocked          | Everyone mocks their inputs at Hour 0 specifically so no one is ever blocked waiting on someone else — if stuck, ping Person 1/Person 5 (integration leads) immediately rather than losing hours silently.   |
