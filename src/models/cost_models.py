"""Resource specs and cost comparison objects.

Description: Pydantic models representing baseline vs target GCP resource
             specs and their computed cost/savings comparisons.
Need: The Cost Agent and Infra Agent must agree on a single, typed
      representation of "what resources cost what" to avoid mismatched units
      or currencies.
Motive: Make cost comparisons that reach the Gate 3 HITL review reliable and
        machine-verifiable.
"""

from pydantic import BaseModel, Field


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

    service_name: str = Field(description="GCP service name, e.g. 'Cloud Run', 'GCE', 'Cloud SQL'.")
    sku_description: str = Field(description="Human-readable description of the priced SKU, e.g. '2 vCPU × 3 instances'.")
    quantity: float = Field(description="Number of units consumed per month.")
    unit: str = Field(description="Billing unit, e.g. 'vCPU/month', 'GB/month', 'million requests'.")
    unit_price_usd: float = Field(description="Price per unit in USD (from live Billing Catalog API or fallback rates).")
    monthly_cost_usd: float = Field(description="Total monthly cost in USD for this line item (quantity × unit_price_usd).")


class ArchitectureInput(BaseModel):
    """Request body for the /api/cost/estimate endpoint."""

    architecture_text: str = Field(
        description=(
            "Plain-English description of the GCP architecture to price. "
            'Example: "3 Cloud Run services (2 vCPU, 1 GB RAM each), '
            '1 Cloud SQL db-n1-standard-2, 500 GB GCS bucket".'
        )
    )
    region: str = Field(default="us-central1", description="GCP region used for pricing lookups.")


class ArchitectureCostEstimate(BaseModel):
    """Full cost breakdown returned by CostScalingAgent.estimate_from_architecture()."""

    services: list[ServiceCostItem] = Field(description="Per-service line items with individual costs.")
    total_monthly_cost_usd: float = Field(description="Sum of all service line items in USD.")
    region: str = Field(description="GCP region the estimate was calculated for.")
    parsed_services_count: int = Field(description="Number of distinct services parsed from the input text.")
    disclaimer: str = Field(
        default=(
            "Estimates are based on public GCP list pricing; actual costs may vary "
            "depending on discounts, sustained-use savings, and committed-use contracts."
        ),
        description="Pricing disclaimer.",
    )
