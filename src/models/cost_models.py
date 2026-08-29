"""Resource specs and cost comparison objects.

Description: Pydantic models representing baseline vs target GCP resource
             specs and their computed cost/savings comparisons.
Need: The Cost Agent and Infra Agent must agree on a single, typed
      representation of "what resources cost what" to avoid mismatched units
      or currencies.
Motive: Make cost comparisons that reach the Gate 3 HITL review reliable and
        machine-verifiable.
"""

from pydantic import BaseModel


class ResourceSpec(BaseModel):
    resource_type: str
    sku_id: str
    quantity: float
    region: str


class CostComparison(BaseModel):
    baseline_monthly_cost: float
    target_monthly_cost: float
    estimated_savings_pct: float


class ServiceCostItem(BaseModel):
    """One line-item in an architecture cost breakdown."""

    service_name: str
    sku_description: str
    quantity: float
    unit: str
    unit_price_usd: float
    monthly_cost_usd: float


class ArchitectureInput(BaseModel):
    """Request body for the /api/cost/estimate endpoint."""

    architecture_text: str
    region: str = "us-central1"


class ArchitectureCostEstimate(BaseModel):
    """Full cost breakdown returned by CostScalingAgent.estimate_from_architecture()."""

    services: list[ServiceCostItem]
    total_monthly_cost_usd: float
    region: str
    parsed_services_count: int
    disclaimer: str = (
        "Estimates are based on public GCP list pricing; actual costs may vary "
        "depending on discounts, sustained-use savings, and committed-use contracts."
    )
