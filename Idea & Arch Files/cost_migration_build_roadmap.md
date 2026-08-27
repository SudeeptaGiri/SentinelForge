# Roadmap & Step-by-Step Implementation Plan: Cost Optimization & Automated Infrastructure Builder

## Executive Summary

This document provides a complete **Roadmap and Implementation Plan** for an autonomous system that:
1. **Analyzes Workloads & Costs**: Measures baseline resource utilization and estimates monthly GCP costs across platforms (GCE VMs, GKE, Cloud Run).
2. **Generates Architectural Optimization Suggestions**: Recommends cost-effective, cloud-native target platforms (e.g., migrating legacy GCE VMs to Cloud Run or GKE Autopilot) with cost reduction calculations.
3. **Automates Infrastructure Building & Code Refactoring**: Auto-generates production-grade Infrastructure-as-Code (Terraform HCL), Kubernetes/Cloud Run service specs, and Cloud Build CI/CD automation pipelines.
4. **Enforces Security & HITL Governance**: Runs pre-commit security checks and gates production deployment behind explicit human sign-off.

---

## 1. System End-to-End Workflow Architecture

```mermaid
flowchart TD
    subgraph Phase1["1. Workload & Cost Analysis"]
        InputSpec[Workload Specification\n(CPU, RAM, Disks, Traffic)]
        CostEngine[GCP Cost Analyzer Engine\n(Billing API Rates)]
        InputSpec --> CostEngine
    end

    subgraph Phase2["2. Recommendation & Arch Refactoring"]
        CostEngine --> Suggester[Migration & Optimization Suggester]
        Suggester --> RecReport[Cost Optimization Report\n(e.g., 68.5% Cost Reduction)]
    end

    subgraph Phase3["3. Automated Artifact Building"]
        RecReport --> InfraBuilder[GCP Infrastructure Builder Engine]
        InfraBuilder --> TF[Terraform HCL\n(google_cloud_run_v2_service)]
        InfraBuilder --> YAML[Cloud Run Service YAML]
        InfraBuilder --> CB[Cloud Build CI/CD Pipeline\n(cloudbuild.yaml)]
    end

    subgraph Phase4["4. Validation & Governance"]
        TF --> Validation[Terraform Validate & Security Scan]
        YAML --> Validation
        Validation --> HITL[Human-in-the-Loop Approval Gate]
        HITL -->|Approved| Deploy[Cloud Build Ephemeral Staging Deploy]
    end
```

---

## 2. Step-by-Step Implementation Plan

### Step 1: Implement Workload Cost Analysis Module (`cost_analyzer.py`)
- **Objective**: Parse resource configurations (CPU, RAM, storage, egress traffic) and compute monthly cost estimates for GCE, GKE, and Cloud Run.
- **Key Logic**:
  - Implement pricing models based on official GCP SKU rates (or Cloud Billing API).
  - Include duty-cycle scaling assumptions for serverless workloads (e.g., Cloud Run active concurrency duty cycles).
  - Output structured cost breakdown objects (`CostEstimate`).

### Step 2: Implement Optimization & Migration Reasoner (`migration_suggester.py`)
- **Objective**: Compare baseline workload costs against cloud-native target architectures and produce actionable optimization proposals.
- **Decision Matrix**:
  - **Stateless HTTP/gRPC API Workloads** $\rightarrow$ **Cloud Run** (Serverless, auto-scale to zero, up to 70%+ savings).
  - **Stateful / Microservice Mesh Workloads** $\rightarrow$ **GKE Autopilot** (Managed K8s nodes, resource-based billing).
  - **Legacy OS Monoliths** $\rightarrow$ **GCE E2/N2 Right-Sizing**.
- **Outputs**: `MigrationPlan` containing baseline cost, target cost, monthly savings ($ and %), rationale, and required architectural changes.

### Step 3: Implement Automated Infrastructure Builder (`infra_builder.py`)
- **Objective**: Programmatically construct production-grade deployable artifacts based on the migration recommendation.
- **Artifacts Generated**:
  1. **Terraform HCL (`main.tf`)**:
     - Modern `google_cloud_run_v2_service` or `google_container_cluster` resources.
     - Parameterized inputs for GCP project, region, and container registry URIs.
     - Liveness and readiness probe configurations.
  2. **Cloud Run Service Manifest (`service.yaml`)**:
     - Declarative Knative/Cloud Run YAML spec defining container limits, environment variables, and scaling boundaries.
  3. **Cloud Build CI/CD Pipeline (`cloudbuild.yaml`)**:
     - Step 1: Docker build container image.
     - Step 2: SAST / Vulnerability scan (Trivy / Strix).
     - Step 3: Push image to Artifact Registry.
     - Step 4: Ephemeral staging environment deployment.

### Step 4: Implement Pre-Deployment Security & Syntax Verification (`validator.py`)
- **Objective**: Ensure auto-generated code passes syntax and security checks before human review.
- **Verification Tools**:
  - `terraform validate` & `tflint` for HCL correctness.
  - `tfsec` / `checkov` to detect insecure IaC patterns (e.g., unrestricted IAM bindings).
  - YAML schema linting.

### Step 5: Implement Human-in-the-Loop (HITL) Gate (`approval_gate.py`)
- **Objective**: Prevent automated code mutation or infrastructure deployment without explicit human review.
- **Workflow**:
  - Generate a visual diff / summary report comparing baseline architecture vs target architecture.
  - Present an interactive approval prompt via Gemini Enterprise UI or Slack/ChatOps webhook.
  - Halt deployment pipeline execution until sign-off is received.

### Step 6: Deploy & Automate via Vertex AI Agent Engine
- **Objective**: Package the entire flow into a ADK sub-agent (`MigrationCostAgent`) hosted on Agent Engine.
- **Trigger**: The main `OrchestratorAgent` invokes `MigrationCostAgent` whenever architecture optimization, cost reduction, or cloud migration tasks are requested.

---

## 3. Concrete Code Reference Architecture

Below is the complete reference module structure created for this pipeline:

```
cost_migration_builder/
├── cost_analyzer.py          # GCP Cost Calculation Engine (GCE, GKE, Cloud Run)
├── migration_suggester.py    # Rule-Based & LLM Migration Reasoner
├── infra_builder.py          # Automated HCL / YAML / Cloud Build Code Generator
└── build_artifacts/          # Generated Output Directory
    ├── main.tf               # Production-ready Terraform HCL
    ├── service.yaml          # Declarative Cloud Run Service Spec
    └── cloudbuild.yaml       # CI/CD Deployment Pipeline
```

### Generated Artifact Example: `main.tf` Snippet
```hcl
resource "google_cloud_run_v2_service" "app_service" {
  name     = "payment-gateway-service"
  location = var.gcp_region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "4"
          memory = "16Gi"
        }
      }

      startup_probe {
        http_get { path = "/healthz" }
        initial_delay_seconds = 5
      }
    }
  }
}
```

---

## 4. Governance & Safety Guardrails

| Guardrail Layer | Control Mechanism | Action |
| :--- | :--- | :--- |
| **IaC Static Analysis** | `checkov` / `tfsec` scanning on generated `main.tf` | Blocks build if critical security misconfigurations exist |
| **Pricing Buffer** | 15% safety factor added to serverless estimations | Prevents underestimating network egress / storage costs |
| **Sandbox Ephemeral Deploy** | Deploy exclusively to isolated staging projects | Keeps production untouched during validation |
| **Human Approval Gate** | Gemini Enterprise UI modal approval | Requires engineer click before executing `terraform apply` |
