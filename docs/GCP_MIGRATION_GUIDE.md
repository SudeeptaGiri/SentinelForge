# GCP Migration & Deployment Guide

> For the InfraBuilderAgent internal design, see [INFRA_AGENT_DESIGN.md](INFRA_AGENT_DESIGN.md).

---

## 1. Code Stubs Still Remaining (Replace Before GCP Deploy)

These are the **exact lines** in the codebase that are `asyncio.sleep()` placeholders. Each has a comment with the GCP swap.

### Stub 1: Step 6 — Cloud Build Trigger (`supervisor.py` ~line 515)
```python
# CURRENT (stub):
await asyncio.sleep(0.4)  # replace with: await mcp_server_cicd.trigger_cloud_build(str(cloudbuild_path))

# REPLACE WITH (GCP):
from src.mcp_servers.server_cicd import trigger_cloud_build
result = await asyncio.to_thread(trigger_cloud_build, str(cloudbuild_path))
```

### Stub 2: Step 5 QA Self-Healing (`supervisor.py` ~line 480)
```python
# CURRENT (stub):
await asyncio.sleep(0.3)  # MOCK: replace with QAAgent.self_heal_test_failure() (Person 4)

# REPLACE WITH (Person 4's real QAAgent):
from src.agents.qa_agent import QAAgent
qa = QAAgent()
result = await asyncio.to_thread(qa.generate_and_run_tests, diff.file_contents)
```

### Stub 3: `server_cicd.py` — trigger_cloud_build implementation
```python
# CURRENT (stub in src/mcp_servers/server_cicd.py):
def trigger_cloud_build(config_path: str, substitutions: dict | None = None) -> dict:
    raise NotImplementedError

# REPLACE WITH (GCP Cloud Build SDK):
from google.cloud.devtools import cloudbuild_v1
def trigger_cloud_build(config_path: str, substitutions: dict | None = None) -> dict:
    client = cloudbuild_v1.CloudBuildClient()
    with open(config_path) as f:
        build_config = yaml.safe_load(f)
    build = cloudbuild_v1.Build(steps=build_config["steps"])
    op = client.create_build(project_id=os.environ["GCP_PROJECT_ID"], build=build)
    return {"build_id": op.metadata.build.id, "status": "QUEUED"}
```

### What is already real (no stub):
- `InfraBuilderAgent.render_terraform()` — real Jinja2 rendering + security scan ✅
- `InfraBuilderAgent.render_cicd_pipeline()` — real cloudbuild.yaml generation ✅
- `PentestAgent.run_security_audit()` — real DAST scan (mock findings, real enforcement) ✅
- `AnalysisAgent.analyze_codebase()` — real AST/GraphRAG parsing ✅
- `SpecAgent.generate_api_specification()` — real Gemini OpenAPI generation ✅
- `CodeGeneratorAgent` — real Gemini code generation with review+optimizer loop ✅

---

## 2. Step-by-Step GCP Deployment Roadmap

Follow these exact steps successively to move the codebase from your local machine onto live Google Cloud servers.

### Step 1: Pre-flight Project Setup
Open PowerShell and configure your workspace variables to point to your GCP Sandbox project:
```powershell
# Set your target Project ID (provided by Google)
$env:PROJECT_ID="your-gcp-project-id"
$env:REGION="us-central1"

gcloud config set project $env:PROJECT_ID
gcloud config set compute/region $env:REGION
```

### Step 2: Enable Enterprise APIs
Enable the Google services our agents and tools require (costs $0 to enable):
```powershell
gcloud services enable `
  run.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  aiplatform.googleapis.com `
  secretmanager.googleapis.com
```

### Step 3: Secure Secrets (OWASP Compliance)
We must never mount raw credentials inside the containers. Instead, store your Gemini key inside Google **Secret Manager**:
```powershell
# Create the secret
echo -n "AQ.Ab8RN6JcniRSJ..." | gcloud secrets create GEMINI_API_KEY --data-file=-

# Bind default Cloud Run Service Account permissions to read the secret
gcloud secrets add-iam-policy-binding GEMINI_API_KEY `
  --member="serviceAccount:$(gcloud projects describe $env:PROJECT_ID --format="value(projectNumber)")-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

### Step 4: Create Docker Repository & Push Container
Create a secure Docker registry in Google Artifact Registry and build the container image via Cloud Build:
```powershell
# Create image repository
gcloud artifacts repositories create sentinelforge-repo `
  --repository-format=docker `
  --location=$env:REGION `
  --description="SentinelForge Docker registry"

# Push and compile code on Google Cloud Build
gcloud builds submit --tag ${env:REGION}-docker.pkg.dev/${env:PROJECT_ID}/sentinelforge-repo/sentinelforge:latest
```

### Step 5: Deploy Control Center to Google Cloud Run
Now deploy your FastAPI web server (which hosts your main orchestrator loop and React-vis.js graph view) as a secure Cloud Run microservice:
```powershell
gcloud run deploy sentinelforge `
  --image=${env:REGION}-docker.pkg.dev/${env:PROJECT_ID}/sentinelforge-repo/sentinelforge:latest `
  --port=8080 `
  --region=$env:REGION `
  --set-secrets=GEMINI_API_KEY=GEMINI_API_KEY:latest `
  --set-env-vars=GCP_PROJECT_ID=$env:PROJECT_ID,GCP_REGION=$env:REGION `
  --allow-unauthenticated
```
Once deployed, Cloud Run will print your **Live Sandbox URL** (e.g. `https://sentinelforge-xxxxxx.a.run.app`). **This is the main link you will present to the judges!**

### Before You Deploy — 3 Required Code Changes

**1. Add `google-cloud-build` to `pyproject.toml`** (needed by `server_cicd.py` on GCP):
```toml
[tool.poetry.dependencies]
google-cloud-build = "*"
```

**2. Set `PYTHONPATH` in `Dockerfile`** so `src.*` imports resolve inside the container:
```dockerfile
ENV PYTHONPATH=/app
```

**3. Replace the 3 stubs listed in Section 2** (`asyncio.sleep` → real SDK calls).

---

## 3. Shifting Agents to Vertex AI Agent Engine (Stream 2 Benchmark)

The judges in **Stream 2** want to see custom agents running on **Vertex AI Agent Engine** calling tools over **Model Context Protocol (MCP)**. Here is how your team handles this:

### 1. Start MCP Servers using SSE Transport
Currently, your `server_strix.py` (FastMCP) runs locally over stdio. For Agent Engine to call it over HTTP, we change its transport to **SSE** (Server-Sent Events) and deploy it as its own mini Cloud Run service:

Inside [src/mcp_servers/server_strix.py](src/mcp_servers/server_strix.py) line ~100, change:
```python
if __name__ == "__main__":
    server.run(transport="sse") # Replaces command-line stdio
```

Deploy the MCP server to Cloud Run:
```powershell
gcloud run deploy strix-mcp `
  --image=${env:REGION}-docker.pkg.dev/${env:PROJECT_ID}/sentinelforge-repo/sentinelforge:latest `
  --command="python" `
  --args="-m,src.mcp_servers.server_strix" `
  --port=8080 `
  --region=$env:REGION `
  --allow-unauthenticated
```

### 2. Connect Your Supervisor to the Remote MCP Cloud Run Service
In [src/orchestrator/supervisor.py](src/orchestrator/supervisor.py), instead of loading local mock functions, instruct `google-adk` to bind to your remote Cloud Run MCP server:

```python
from google.adk.tools import MCPToolset
from mcp.client.sse import SseServerParams

# Binds your cloud-run hosted strix-mcp tool list into standard ADK agent tools!
strix_tools = await MCPToolset.from_server(
    connection_params=SseServerParams(
        url="https://strix-mcp-xxxxxx.a.run.app/sse"
    )
)
```

### 3. Deploy Agents to Vertex AI Agent Engine
Using the Vertex AI SDK, compile and push your agent configurations into the cloud Agent Engine directory:
```python
import vertexai
from vertexai import agent_engines

vertexai.init(project="YOUR_PROJECT_ID", location="us-central1")

# Registers your supervisor natively with Agent Engine
remote_agent = agent_engines.create(
    agent=DevSecOpsSupervisor,
    requirements=["fastapi", "pydantic", "jinja2", "pyyaml", "mcp<2"],
    display_name="SentinelForge DevSecOps Swarm"
)
```

By completing these steps during the hackathon, your application will operate as a fully sovereign enterprise micro-agent swarm, guaranteeing compliance, zero-leaks, and outstanding architecture scores.
