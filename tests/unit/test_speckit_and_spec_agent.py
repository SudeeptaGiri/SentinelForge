"""Unit tests for specKit engine and SpecAgent."""

import pytest
from src.agents.spec_agent import SpecAgent, generate_api_specification
from src.models.schemas import SpecResult, WorkloadSpec
from src.utils.speckit import (
    parse_spec,
    validate_openapi_spec,
    extract_endpoints,
    extract_data_models,
    derive_workload_spec_from_concept,
)


def test_speckit_validation():
    valid_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Users API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "summary": "List users",
                    "responses": {"200": {"description": "OK"}}
                }
            }
        }
    }
    val_res = validate_openapi_spec(valid_spec)
    assert val_res["valid"] is True
    assert len(val_res["errors"]) == 0

    invalid_spec = {"paths": {}}
    val_inv = validate_openapi_spec(invalid_spec)
    assert val_inv["valid"] is False
    assert len(val_inv["errors"]) > 0


def test_speckit_extraction():
    sample_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Orders Service", "version": "2.0.0"},
        "paths": {
            "/orders": {
                "get": {"summary": "Get orders", "responses": {"200": {}}},
                "post": {"summary": "Create order", "responses": {"201": {}}}
            }
        },
        "components": {
            "schemas": {
                "Order": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "amount": {"type": "number"}}
                }
            }
        }
    }
    endpoints = extract_endpoints(sample_spec)
    assert len(endpoints) == 2
    methods = {e["method"] for e in endpoints}
    assert "GET" in methods and "POST" in methods

    models = extract_data_models(sample_spec)
    assert len(models) == 1
    assert models[0]["name"] == "Order"
    assert "amount" in models[0]["properties"]


def test_speckit_phrasing_robustness():
    dummy_spec = {"info": {"title": "High Load Service"}, "paths": {}}

    # Hyphenated concept
    hyphen_res = derive_workload_spec_from_concept(dummy_spec, "A high-throughput streaming API with Spanner persistence")
    assert hyphen_res.cpu_cores == 2.0
    assert hyphen_res.ram_gb == 4.0
    assert hyphen_res.monthly_requests == 1000000
    assert hyphen_res.is_stateful is True

    # Spaced concept
    spaced_res = derive_workload_spec_from_concept(dummy_spec, "A high throughput streaming API with Spanner persistence")
    assert spaced_res.cpu_cores == 2.0
    assert spaced_res.ram_gb == 4.0
    assert spaced_res.monthly_requests == 1000000
    assert spaced_res.is_stateful is True

    # Standard stateless concept
    standard_res = derive_workload_spec_from_concept(dummy_spec, "A simple CRUD product catalog service")
    assert standard_res.cpu_cores == 1.0
    assert standard_res.ram_gb == 2.0
    assert standard_res.monthly_requests == 100000
    assert standard_res.is_stateful is False


def test_spec_agent_generate_spec():
    agent = SpecAgent()
    assert agent.adk_agent.name == "spec_agent"
    tool_names = [getattr(t, "__name__", str(t)) for t in agent.adk_agent.tools]
    assert "generate_api_specification" in tool_names
    assert "validate_spec_text" in tool_names

    result = agent.generate_api_spec("Build a payments webhook service for Cloud Run")
    assert isinstance(result, SpecResult)
    assert result.spec_type == "OpenAPI"
    assert len(result.endpoints) >= 1
    assert len(result.data_models) >= 1
    assert result.workload_spec is not None

    tool_res = generate_api_specification("Build a payments webhook service for Cloud Run")
    assert isinstance(tool_res, dict)
    assert tool_res["status"] == "success"
    assert "spec_yaml" in tool_res
    assert "openapi: 3.1.0" in tool_res["spec_yaml"]
    assert len(tool_res["endpoints"]) >= 1
    assert len(tool_res["data_models"]) >= 1
