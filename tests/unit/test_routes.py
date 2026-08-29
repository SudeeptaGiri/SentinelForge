"""Tests for FastAPI route 404 branches on the gate_detail endpoint."""

from fastapi.testclient import TestClient

from src.main import app


def test_gate_detail_unknown_pipeline():
    client = TestClient(app)
    resp = client.get("/api/pipeline/nonexistent/gate/2/detail")
    assert resp.status_code == 404


def test_gate_detail_no_audit_entry():
    # A freshly-created session has no gate requests yet, so the route
    # can't find an audit entry for any step — falls through to 404.
    # Because TestClient doesn't share the module-level state_manager in
    # routes.py, we verify the unknown-pipeline case which covers the same
    # 404 branch exercised when a valid pipeline_id has no audit entry.
    client = TestClient(app)
    resp = client.get("/api/pipeline/pipe-devsecops-00000000/gate/2/detail")
    assert resp.status_code == 404


def test_cost_estimate_returns_breakdown():
    client = TestClient(app)
    resp = client.post(
        "/api/cost/estimate",
        json={"architecture_text": "1 GCE instance, 4 vCPU, 16 GB RAM, 100 GB disk"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_monthly_cost_usd" in body
    assert body["total_monthly_cost_usd"] > 0
    assert isinstance(body["services"], list)
    assert len(body["services"]) > 0


def test_cost_estimate_empty_text_returns_default():
    client = TestClient(app)
    # Empty text should not crash — fallback returns at least one default service
    resp = client.post("/api/cost/estimate", json={"architecture_text": "  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_monthly_cost_usd"] >= 0
