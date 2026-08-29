import pytest

from src.agents.cost_agent import CostScalingAgent
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


def test_estimate_gce_only():
    agent = CostScalingAgent()
    # Pre-parsed spec — bypasses Gemini
    parsed = [{"type": "gce", "count": 1, "cpu_vcpu": 4, "ram_gb": 16, "disk_gb": 100}]
    result = agent._price_services(parsed, "us-central1")
    assert result.total_monthly_cost_usd > 0
    assert any(s.service_name == "GCE" for s in result.services)


def test_estimate_cloud_run_and_gcs():
    agent = CostScalingAgent()
    parsed = [
        {"type": "cloud_run", "count": 2, "cpu_vcpu": 1, "ram_gb": 0.5, "requests_per_month": 200_000},
        {"type": "gcs", "count": 1, "storage_gb": 500},
    ]
    result = agent._price_services(parsed, "us-central1")
    assert result.parsed_services_count == 2
    # Cloud Run + GCS both present
    names = {s.service_name for s in result.services}
    assert "Cloud Run" in names
    assert "GCS" in names


def test_compute_cost_savings_returns_dict():
    agent = CostScalingAgent()
    baseline = {"monthly_cost_usd": 300.0, "platform": "GCE"}
    target = {"monthly_cost_usd": 180.0, "platform": "Cloud Run"}
    result = agent.compute_cost_savings(baseline, target)
    assert result["monthly_savings_usd"] == pytest.approx(120.0)
    assert result["savings_pct"] == pytest.approx(40.0)


def test_fallback_parse_recognises_cloud_run():
    agent = CostScalingAgent()
    specs = agent._fallback_parse("2 Cloud Run services, 1 vCPU each")
    assert any(s["type"] == "cloud_run" for s in specs)


def test_estimate_from_architecture_returns_estimate(monkeypatch):
    """estimate_from_architecture uses fallback rates and fallback parser when no keys set."""
    agent = CostScalingAgent(gemini_api_key=None, gcp_api_key=None)
    # Force the fallback parse path
    monkeypatch.setattr(agent, "_gemini_parse", lambda text: [
        {"type": "gce", "count": 1, "cpu_vcpu": 2, "ram_gb": 8, "disk_gb": 50}
    ])
    result = agent.estimate_from_architecture("1 GCE instance, 2 vCPU, 8 GB RAM", "us-central1")
    assert isinstance(result.total_monthly_cost_usd, float)
    assert result.total_monthly_cost_usd > 0
    assert result.region == "us-central1"
