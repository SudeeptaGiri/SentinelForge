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
