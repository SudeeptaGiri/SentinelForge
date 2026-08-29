# InfraBuilderAgent — Design & Integration Reference

**File:** `src/agents/infra_agent.py`  
**Owner:** Person 5 (Pentest/UI/Integration)  
**ADK web test:** `adk web agents_web/infra_agent`

---

## How It Connects to Every Other Agent

```
User (React UI)
      │ POST /api/pipeline/start  {repo_path, app_name, intent}
      ▼
AsyncDevSecOpsSupervisor (orchestrator/supervisor.py)
      │
      ├─ Step 1 ──> AnalysisAgent.analyze_codebase(repo_path)
      │              Returns: detected_platform, framework, summary, graph_summary
      │
      ├─ Step 2 ──> SpecAgent.generate_api_specification(concept)
      │              Returns: MigrationPlan  {baseline_cost, target_cost, savings_pct, rationale}
      │              Also stores: session.spec_data, session.plan_data  (drives React panel)
      │
      ├─ Step 3 ──> CodeGeneratorAgent.generate_from_spec(spec_data, target_platform)
      │              Returns: CodeDiff  {files_changed, file_contents, branch_name}
      │              Writes to disk: generated_output/<pipeline_id>/Dockerfile
      │                              generated_output/<pipeline_id>/app/healthz.py
      │                              generated_output/<pipeline_id>/service.yaml
      │
      ├─ Step 4 ──> InfraBuilderAgent  ◄── THIS AGENT
      │              Input:  MigrationPlan (from Step 2) + session.app_name + session.pipeline_id
      │              Does:
      │                1. Renders templates/terraform/cloud_run.tf.j2  → main.tf
      │                2. Renders templates/cicd/cloudbuild.yaml.j2    → cloudbuild.yaml
      │                3. Optionally calls Gemini Flash to enrich HCL with labels/variable blocks
      │                4. Scans HCL against config/security_rules.yaml (CIS/NIST — blocks allUsers, 0.0.0.0/0)
      │                5. Writes both: generated_output/<pipeline_id>/main.tf
      │                               generated_output/<pipeline_id>/cloudbuild.yaml
      │              Returns: {validation_passed, tf_hcl, cicd_yaml}
      │
      ├─ Step 5 ──> QAAgent (self-heal loop) + PentestAgent.run_security_audit(staging_url)
      │              PentestAgent reads security_rules.yaml, enforces host allowlist
      │              Returns: SecurityAuditReport  {findings, overall_risk}
      │
      └─ Step 6 ──> _step_deploy(infra)
                     Reads: generated_output/<pipeline_id>/cloudbuild.yaml  ← written by THIS agent in Step 4
                     Reads: generated_output/<pipeline_id>/main.tf           ← written by THIS agent in Step 4
                     Stubs:  asyncio.sleep(0.4)  → replace with mcp_server_cicd.trigger_cloud_build()
                     Returns: {url, status, cloudbuild_yaml path, main_tf path}
```

---

## Method Reference

| Method | Input | Output | Real / Stub |
|---|---|---|---|
| `render_terraform(spec)` | `dict` (service_name, platform, cpu, memory, image_uri, region) | Terraform HCL string | **Real** |
| `render_cicd_pipeline(spec)` | `dict` (service_name, region, image_uri) | cloudbuild.yaml string | **Real** |
| `_enrich_hcl_with_llm(hcl, spec)` | raw HCL + spec dict | enriched HCL with labels/vars | **Real** (Gemini Flash, graceful fallback) |
| `_scan_hcl_for_violations(hcl)` | raw HCL string | raises `ValueError` on violation | **Real** (reads `security_rules.yaml`) |
| `generate_terraform_tool(...)` | flat kwargs | HCL string | ADK tool wrapper — **Real** |
| `generate_cicd_pipeline_tool(...)` | flat kwargs | YAML string | ADK tool wrapper — **Real** |

---

## Template Files Used

| Template | Renders to | Used for |
|---|---|---|
| `templates/terraform/cloud_run.tf.j2` | `main.tf` | Cloud Run v2 serverless deployment |
| `templates/terraform/gke_autopilot.tf.j2` | `main.tf` | GKE Autopilot Kubernetes cluster |
| `templates/cicd/cloudbuild.yaml.j2` | `cloudbuild.yaml` | GCP Cloud Build CI/CD pipeline (build → push → deploy) |

---

## Security Policy Enforcement

Reads `config/security_rules.yaml → security.iac_policy.blocked_iac_patterns`.  
Currently blocks:

| Pattern | Why blocked |
|---|---|
| `allUsers` | Public IAM binding — exposes service to the internet without auth |
| `allAuthenticatedUsers` | Overly broad Google account access |
| `0.0.0.0/0` | Unrestricted CIDR on firewall rules |

If any pattern is matched in the rendered HCL, a `ValueError` is raised **before** any file is written to disk, preventing an insecure artefact from reaching the HITL gate or Cloud Build.

---

## How to Test Locally via ADK Web UI

```powershell
$env:PYTHONPATH="."
$env:GEMINI_API_KEY="your-key"
.\.venv\Scripts\adk.exe web agents_web/infra_agent
# Open http://localhost:8000
```

**Test prompts:**
- `"Generate Terraform for a Cloud Run service called payment-api in us-east1 with 2 CPU and 1Gi memory"`
- `"Generate a Cloud Build pipeline for service inventory-service"`
- `"What happens if the Terraform contains allUsers binding?"` — agent should refuse

---

## On GCP — What Changes

When `_step_deploy` runs on GCP, the `asyncio.sleep(0.4)` placeholder is replaced with:

```python
from src.mcp_servers.server_cicd import trigger_cloud_build
result = await asyncio.to_thread(trigger_cloud_build, str(cloudbuild_path))
```

This passes the `cloudbuild.yaml` path that `InfraBuilderAgent` wrote in Step 4 directly to the Cloud Build API.  
Cloud Build then:
1. Reads the `cloudbuild.yaml` steps (build image → push to Artifact Registry → deploy to Cloud Run).
2. Provisions the Cloud Run service described in `main.tf` (via `terraform apply`).
3. Returns the live URL.
