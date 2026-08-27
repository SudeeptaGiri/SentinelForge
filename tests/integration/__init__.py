"""Integration tests with GCP mock services.

Description: Tests verifying interaction between agents, MCP servers, and
             (mocked) GCP services (Billing, Cloud Build, Artifact Registry).
Need: Unit tests alone can't catch contract mismatches between components
      and the external services they call.
Motive: Validate integration boundaries without incurring real GCP cost or
        requiring live credentials in CI.
"""
