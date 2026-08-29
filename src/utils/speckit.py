"""specKit: OpenAPI 3.1 Spec Formulation and Validation Engine.

Description: Utilities for parsing, validating, and extracting endpoints and Pydantic
             models from OpenAPI 3.1 definitions generated from user concept prompts.
Need: Greenfield and Spec Alignment scenarios require formal machine-readable contracts
      before downstream code generation and infrastructure provisioning.
Motive: Ensure all API specs conform to standard OpenAPI specifications, catching syntax
        or contract errors early.
"""

import json
import re
from typing import Any, Dict, List
import yaml

from src.models.schemas import WorkloadSpec


def parse_spec(raw_spec_text: str) -> Dict[str, Any]:
    """Parses raw YAML or JSON specification string into a dictionary."""
    clean_text = raw_spec_text.strip()
    if clean_text.startswith("```yaml") or clean_text.startswith("```json"):
        clean_text = re.sub(r"^```(?:yaml|json)?\n", "", clean_text)
        clean_text = re.sub(r"\n```$", "", clean_text)

    try:
        return yaml.safe_load(clean_text) or {}
    except Exception:
        try:
            return json.loads(clean_text)
        except Exception:
            return {}


def validate_openapi_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validates OpenAPI 3.0/3.1 document structure.

    Args:
        spec: Parsed OpenAPI specification dictionary.

    Returns:
        Dictionary containing 'valid' (bool) and 'errors' (list of string descriptions).
    """
    errors = []
    if not isinstance(spec, dict):
        return {"valid": False, "errors": ["Specification must be a dictionary/object."]}

    if "openapi" not in spec and "swagger" not in spec:
        errors.append("Missing required 'openapi' version field (e.g., '3.1.0').")

    if "info" not in spec or not isinstance(spec["info"], dict):
        errors.append("Missing required 'info' block.")
    else:
        if "title" not in spec["info"]:
            errors.append("Missing required 'info.title' field.")
        if "version" not in spec["info"]:
            errors.append("Missing required 'info.version' field.")

    if "paths" not in spec or not isinstance(spec["paths"], dict):
        errors.append("Missing required 'paths' section.")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def extract_endpoints(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts endpoint details (path, methods, summary, responses) from OpenAPI spec."""
    endpoints = []
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return endpoints

    valid_methods = {"get", "post", "put", "delete", "patch", "options", "head"}
    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() in valid_methods and isinstance(op, dict):
                endpoints.append({
                    "path": path_str,
                    "method": method.upper(),
                    "operation_id": op.get("operationId", f"{method}_{path_str.replace('/', '_')}"),
                    "summary": op.get("summary", ""),
                    "description": op.get("description", ""),
                    "parameters": op.get("parameters", []),
                    "responses": list(op.get("responses", {}).keys())
                })
    return endpoints


def extract_data_models(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts schema definitions from components.schemas."""
    models = []
    schemas = spec.get("components", {}).get("schemas", {})
    if isinstance(schemas, dict):
        for name, schema_def in schemas.items():
            if isinstance(schema_def, dict):
                models.append({
                    "name": name,
                    "type": schema_def.get("type", "object"),
                    "properties": list(schema_def.get("properties", {}).keys()),
                    "required": schema_def.get("required", []),
                })
    return models


def derive_workload_spec_from_concept(
    spec: Dict[str, Any],
    concept_prompt: str
) -> WorkloadSpec:
    """Estimates initial sizing and workload profile from spec complexity and concept.

    Normalizes phrasing and punctuation so hyphenated and spaced keywords
    (e.g., 'high-throughput', 'high throughput', 'session-store') match reliably.
    """
    title = spec.get("info", {}).get("title", "greenfield-service")
    slug_name = re.sub(r'[^a-zA-Z0-9_-]', '-', title.lower()).strip('-') or "greenfield-service"

    endpoints = extract_endpoints(spec)

    # Normalize concept text: replace hyphens/underscores with space for robust matching
    normalized_concept = re.sub(r'[-_]+', ' ', concept_prompt.lower())

    # High-throughput indicators
    high_throughput_patterns = [
        r'\bhigh\s*throughput\b',
        r'\bmillion\b',
        r'\bmassive\b',
        r'\bstreaming\b',
        r'\bbatch\b',
        r'\bscale\b',
        r'\breal\s*time\b',
        r'\bhigh\s*volume\b',
        r'\bdistributed\b'
    ]
    is_high_throughput = any(re.search(pattern, normalized_concept) for pattern in high_throughput_patterns)

    # Stateful indicators
    stateful_patterns = [
        r'\bstateful\b',
        r'\bwebsocket\b',
        r'\bcache\b',
        r'\bsession\s*store\b',
        r'\bspanner\b',
        r'\bsql\b',
        r'\bpostgres\b',
        r'\bdatabase\b',
        r'\bpersistent\b'
    ]
    is_stateful = any(re.search(pattern, normalized_concept) for pattern in stateful_patterns)

    cpu = 2.0 if is_high_throughput or len(endpoints) > 6 else 1.0
    ram = 4.0 if is_high_throughput or len(endpoints) > 6 else 2.0
    disk = 20.0 if is_stateful else 10.0
    requests = 1000000 if is_high_throughput else (500000 if len(endpoints) > 4 else 100000)

    return WorkloadSpec(
        name=slug_name,
        cpu_cores=cpu,
        ram_gb=ram,
        disk_gb=disk,
        monthly_requests=requests,
        is_stateful=is_stateful
    )
