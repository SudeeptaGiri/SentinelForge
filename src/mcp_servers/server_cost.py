"""MCP Server: GCP Cloud Billing API & Pricing Calculator.

Description: MCP tool server wrapping GCP Billing & Pricing API
             (`get_gcp_pricing`).
Need: The Cost Agent needs live, accurate SKU pricing rather than
      hardcoded/stale estimates to produce trustworthy cost comparisons.
Motive: Provide a single, cacheable interface to GCP billing data so all
        cost calculations across the system stay consistent.
"""

server = None  # Server("gcp-cost-mcp") — placeholder until MCP SDK is wired in.


def get_gcp_pricing(sku_ids: list[str], region: str) -> dict:
    """Fetches live SKU pricing from the GCP Cloud Billing API."""
    raise NotImplementedError
