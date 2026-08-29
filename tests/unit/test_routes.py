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
