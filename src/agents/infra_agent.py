"""Terraform HCL & Kubernetes/Cloud Run Manifest Generator.

Description: Generates production-ready Terraform HCL (`main.tf`) and
             Cloud Run/GKE YAML manifests.
Need: Manually writing IaC for every generated app is slow and error-prone;
      it also needs to stay consistent with the cost/scaling decisions made
      upstream.
Motive: Turn the approved cost/scaling plan directly into deployable,
        version-controlled infrastructure code, ready for Gate 3 review.
"""


class InfraBuilderAgent:
    """Renders Terraform HCL and CI/CD manifests from approved templates."""

    def render_terraform(self, resource_spec: dict) -> str:
        raise NotImplementedError
