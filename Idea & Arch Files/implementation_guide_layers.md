# Implementation Guide: How to Build Each Layer (Simple Language + Technical Details)

## How to Read This Document

For every layer of the system, you get 3 things:

1. **What it does** (in plain, simple words)
2. **How to build it** (the actual technical steps)
3. **What to study** (real tools/docs to learn from before/while building)

This is the "how" companion to the architecture diagrams already in [hld_devsecops_agent_architecture.md](hld_devsecops_agent_architecture.md) and [devsecops_full_project_architecture.md](devsecops_full_project_architecture.md).

---

## Quick Reference: All Tools & Services Used

| Tool / Service                     | What it's for                                                 | Free / Paid                | Where to learn it                                                   |
| ---------------------------------- | ------------------------------------------------------------- | -------------------------- | ------------------------------------------------------------------- |
| Google ADK (Agent Development Kit) | Framework to build the agents and connect them together       | Free, open source          | google.github.io/adk-docs                                           |
| Vertex AI Agent Engine             | Runs your agents in the cloud, remembers conversation history | Paid (GCP usage)           | cloud.google.com/vertex-ai/generative-ai/docs/agent-engine          |
| Gemini 2.5 Pro / Flash             | The "brain" (LLM) each agent uses to think/reason             | Paid (per token)           | ai.google.dev/gemini-api/docs                                       |
| Gemini Enterprise                  | Chat UI, login/identity, approval popups                      | Paid (Workspace)           | cloud.google.com/products/gemini-enterprise                         |
| Model Context Protocol (MCP)       | Standard way for agents to call tools                         | Free, open standard        | modelcontextprotocol.io                                             |
| Graphify                           | Reads your codebase and builds a map of it (GraphRAG)         | Depends on project         | Search GitHub, verify exact repo before use                         |
| speckit                            | Turns plain English into API specs (OpenAPI)                  | Depends on project         | Verify exact package on PyPI/GitHub                                 |
| Strix                              | Runs security scans (pentest) on your app                     | Depends on project         | Verify exact repo before use                                        |
| Terraform                          | Writes infrastructure as code (creates cloud resources)       | Free, open source          | developer.hashicorp.com/terraform/docs                              |
| Checkov                            | Scans Terraform files for security mistakes                   | Free, open source          | checkov.io                                                          |
| Trivy (includes old tfsec)         | Scans containers + IaC for vulnerabilities                    | Free, open source          | aquasecurity.github.io/trivy                                        |
| Cloud Build                        | Runs your build/test/deploy pipeline                          | Paid (GCP usage)           | cloud.google.com/build/docs                                         |
| Artifact Registry                  | Stores your built Docker images safely                        | Paid (GCP usage)           | cloud.google.com/artifact-registry/docs                             |
| Cloud Run v2                       | Hosts simple web apps/APIs, scales to zero                    | Paid (GCP usage)           | cloud.google.com/run/docs                                           |
| GKE Autopilot                      | Hosts complex multi-service apps (Kubernetes)                 | Paid (GCP usage)           | cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview |
| Cloud Billing API                  | Gets real GCP prices to calculate cost estimates              | Paid (GCP usage, low cost) | cloud.google.com/billing/docs/apis                                  |
| Cloud IAM                          | Controls who/what can access what                             | Free (part of GCP)         | cloud.google.com/iam/docs                                           |
| Cloud Logging + OpenTelemetry      | Tracks what the agents are doing, for debugging               | Paid (GCP usage)           | cloud.google.com/logging/docs                                       |

---

## Layer 1: Ingress & Identity (The Front Door)

### What it does (simple language)

This is the "front door" of the system. Before any request (a chat message, a webhook from GitHub, a click in the UI) is allowed to reach the agents, we check **who is asking** and **what they're allowed to do**. This stops the AI from doing things the actual human isn't allowed to do.

### How to build it

1. Set up Google Cloud IAM roles — give each type of user (developer, admin) only the permissions they need, nothing extra.
2. Put Identity-Aware Proxy (IAP) in front of your app's entry point so nobody reaches the agent without logging in first.
3. When a request comes in, attach the user's identity token to it, and keep that token attached all the way through the pipeline — every tool call later checks this same token.
4. For automatic triggers (like a GitHub ticket creating a task), use a separate limited-permission service account — not a personal user account.

### What to study

- Google Cloud IAM basics: cloud.google.com/iam/docs
- Identity-Aware Proxy (IAP): cloud.google.com/iap/docs
- OAuth2 login flow for Google: developers.google.com/identity/protocols/oauth2

---

## Layer 2: Orchestrator + Human Approval Gates (The Brain + The Safety Switch)

### What it does (simple language)

This is the manager. It knows the full plan (which steps come next), asks the right specialist to do each step, and — most importantly — **stops and waits for a human to click "approve"** before doing anything risky. It also remembers everything even if the human takes hours or days to respond.

### How to build it

1. Build a simple step list model in code: `step number, name, status (waiting/running/done), which agent handles it`.
2. Use ADK's built-in "Sequential Agent" pattern — this just means: do step 1, wait, do step 2, wait, and so on, instead of one big free-for-all AI loop.
3. Save the pipeline's current state (which step it's on, what's been approved) using Agent Engine's built-in memory — don't build your own database for this, it already exists.
4. Build ONE reusable "ask for approval" function. It shows a summary of what's about to happen, waits for a yes/no/modify answer, and only continues once approved. Use this exact same function for all 5 approval points — don't write 5 different versions.

### What to study

- Google ADK official docs (agents, sessions, tools): google.github.io/adk-docs
- ADK GitHub source code: github.com/google/adk-python
- Vertex AI Agent Engine sessions & memory: cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/overview

---

## Layer 3: Specialist Agents (The Expert Team)

### What it does (simple language)

Each agent is like one expert on a team. One expert reads code, one calculates cost, one writes Terraform, one writes app code, one tests, one checks security. The manager (Layer 2) calls the right expert at the right time.

### 3.1 Analysis Agent (reads existing code)

- **Simple explanation**: Instead of dumping an entire codebase into the AI's memory (too big, too slow, too expensive), it builds a "map" of the code first (which function calls which, which file imports which) and only looks up the relevant parts when needed.
- **How to build**: Run the code-mapping tool once per repo and save the map. Let the agent ask questions against that map instead of reading raw files every time.
- **Study**: Look up "GraphRAG" as the general concept (Microsoft's GraphRAG project is a good reference: github.com/microsoft/graphrag); confirm the exact "Graphify" tool/repo you plan to use before depending on it.

### 3.2 Spec Agent (turns ideas into a technical spec)

- **Simple explanation**: Converts a plain English idea ("build a login system") into a proper technical contract (OpenAPI spec) that both the code-writing agent and the testing agent can follow exactly.
- **How to build**: Prompt the LLM to output OpenAPI YAML, then validate that YAML against the official OpenAPI schema before accepting it (reject and retry if invalid).
- **Study**: OpenAPI Specification: spec.openapis.org

### 3.3 Code Generator Agent (writes/changes code)

- **Simple explanation**: Writes new code or edits existing code, but always as a reviewable "diff" (a before/after comparison), never a silent full rewrite.
- **How to build**: Create a new git branch first, make changes there, then produce a diff for the human to review at Gate 2.
- **Study**: Git basics (branches, diffs): git-scm.com/doc

### 3.4 Cost Agent (calculates cloud costs)

- **Simple explanation**: Cost = price-per-unit × how much you use × how often it's actually running. Adds a safety buffer so estimates aren't too optimistic.
- **How to build**: Call Google's live pricing API instead of hardcoding prices (prices change over time).
- **Study**: Cloud Billing Catalog API: cloud.google.com/billing/v1/how-tos/catalog-api

### 3.5 Infra Agent (writes Terraform/cloud config)

- **Simple explanation**: Rather than letting the AI freely type out infrastructure code (risky — it can make mistakes), the AI just picks a pre-built, tested template and fills in the blanks (project name, region, memory size).
- **How to build**: Store `.tf` template files with placeholders (Jinja2 templates); the agent's job is choosing values, not writing raw syntax.
- **Study**: Terraform language docs: developer.hashicorp.com/terraform/language; Google provider resource docs: registry.terraform.io/providers/hashicorp/google/latest/docs

### 3.6 QA Agent (tests + self-heals)

- **Simple explanation**: Runs the tests. If they fail, it reads the error, tries to fix the code, and re-runs the tests — repeating a limited number of times so it doesn't loop forever.
- **How to build**: Run tests inside Cloud Build (isolated container each time); set a max retry count (e.g., 3 attempts).
- **Study**: Cloud Build configuration: cloud.google.com/build/docs/build-config-file-schema

### 3.7 Pentest Agent (security scanning)

- **Simple explanation**: Scans the deployed app for security holes — but ONLY on the safe testing copy of the app, never the real live app.
- **How to build**: Hard-code a check (not just a prompt instruction) that blocks scanning any address that isn't clearly a staging/sandbox address.
- **Study**: Confirm your exact "Strix" tool source before integrating; as a well-known open-source alternative for reference, look at OWASP ZAP: zaproxy.org

---

## Layer 4: MCP Tool Servers (The Toolbox)

### What it does (simple language)

Instead of each AI agent having its own custom way of calling tools, everything goes through one standard format (MCP). Think of it like a universal power socket — any agent can plug into any tool the same way.

### How to build it

1. Pick the official MCP Python library.
2. For each tool group (code reading, cost lookup, deployment, git, security scan), build one small server exposing a few clearly named functions.
3. Always double-check the AI's input before running anything dangerous (like a terminal command) — never trust it blindly, this prevents a whole category of security bugs.
4. Run each tool server as its own separate small program/container, so if one breaks or gets attacked, the others keep working.

### What to study

- Model Context Protocol overview & spec: modelcontextprotocol.io
- MCP Python SDK: github.com/modelcontextprotocol/python-sdk
- ADK's guide on connecting to MCP tools: search "MCP" inside google.github.io/adk-docs

---

## Layer 5: Cloud Infrastructure (Where It Actually Runs)

### What it does (simple language)

This is the real Google Cloud environment where generated code gets built, tested, and eventually goes live. Nothing here gets touched until it's been checked for mistakes and approved by a human. New apps are first tried in a safe "practice" copy of the cloud, never directly in the real one.

### How to build it

1. **Check before building**: Run `terraform validate`, then a linter (`tflint`), then a security scanner (`checkov` or `trivy`) on every generated Terraform file — if any of these fail, stop and fix before showing it to the human.
2. **Practice environment first**: Deploy first to a separate, temporary Google Cloud project that automatically deletes itself after a few hours — this way a mistake never touches the real, live app.
3. **Deploying simple apps**: Use Cloud Run — it's serverless, so it automatically scales up and down and even scales to zero (no cost) when nobody's using it.
4. **Deploying complex apps**: If the app needs multiple connected services (like Kubernetes), use GKE Autopilot instead — Google manages the servers for you.
5. **Going live for real**: Only after the human clicks final approval, apply the same Terraform to the actual production Google Cloud project — keep this as a completely separate, protected step from the practice environment.

### What to study

- Terraform validate command: developer.hashicorp.com/terraform/cli/commands/validate
- Checkov security scanner: checkov.io
- Trivy (security scanner, replaced tfsec): aquasecurity.github.io/trivy
- Cloud Run v2: cloud.google.com/run/docs
- GKE Autopilot: cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview
- Cloud Build manual approval step (for the final human gate before production): cloud.google.com/build/docs/securing-builds/approve-builds

---

## Security Checklist (Keep the System Safe)

| Danger                                                            | How we prevent it                                                                                                    |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| AI-generated text accidentally running a dangerous system command | Always validate/check inputs before running anything; never run raw AI text directly as a command                    |
| One agent getting more cloud access than it needs                 | Give every agent its own limited permission account, not one shared "admin" account                                  |
| Security scanner being pointed at the real live app by mistake    | Block any scan target that isn't clearly a test/sandbox address, checked in code — not just asked nicely in a prompt |
| Bad/insecure cloud configuration being deployed                   | Always run a security scanner (Checkov/Trivy) on generated infrastructure code before anyone approves it             |
| Passwords/secrets accidentally written into generated code        | Add an automatic secret-scanning step (e.g., gitleaks) before the code review step                                   |
| The self-fixing test loop running forever and costing money       | Set a hard limit on how many times it can retry (e.g., 3 tries, then stop and ask a human)                           |

---

## Suggested Build Order (Fastest Path to a Working Demo)

1. Layer 2 (Orchestrator + Approval Gates) — build this first, it's the core safety mechanism everything else depends on.
2. One full scenario, plain code first (no AI yet) — prove the cost → proposal → approval → build → approval → deploy flow works end-to-end.
3. Layer 4 (MCP wrappers) — wrap the plain code behind MCP tools.
4. Layer 3 (real AI agents) — swap the plain code for actual ADK agents calling those MCP tools.
5. Add the other two scenarios (Greenfield, Ongoing ticket) — they only change how "Analysis" starts; everything after is reused.
6. Layer 5 security hardening (Checkov/Trivy, sandbox TTL) — do this before ever pointing at a real GCP project.
7. Layer 1 (real login/identity) + UI polish — wire this in last, once the core logic already works.
