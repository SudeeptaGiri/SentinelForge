from src.models.cost_models import (
    ArchitectureCostEstimate,
    ArchitectureInput,
    CostComparison,
    ResourceSpec,
    ServiceCostItem,
)


def test_service_cost_item_fields():
    item = ServiceCostItem(
        service_name="Cloud Run",
        sku_description="2 vCPU × 3 instances",
        quantity=6.0,
        unit="vCPU/month",
        unit_price_usd=12.41,
        monthly_cost_usd=74.46,
    )
    assert item.service_name == "Cloud Run"
    assert item.monthly_cost_usd == 74.46


def test_architecture_input_defaults():
    ai = ArchitectureInput(architecture_text="1 GCE n2-standard-2")
    assert ai.region == "us-central1"


def test_architecture_cost_estimate_totals():
    items = [
        ServiceCostItem(service_name="GCE", sku_description="4 vCPU", quantity=4.0,
                        unit="vCPU/month", unit_price_usd=12.41, monthly_cost_usd=49.64),
        ServiceCostItem(service_name="GCS", sku_description="100 GB standard",
                        quantity=100.0, unit="GB/month", unit_price_usd=0.02, monthly_cost_usd=2.0),
    ]
    est = ArchitectureCostEstimate(
        services=items,
        total_monthly_cost_usd=51.64,
        region="us-central1",
        parsed_services_count=2,
    )
    assert est.total_monthly_cost_usd == 51.64
    assert est.parsed_services_count == 2
    assert "vary" in est.disclaimer
