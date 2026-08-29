"""GCP Cost & Scaling Optimization Agent.

Description: Estimates GCP resource costs from a free-text architecture
             description. Uses Gemini for text parsing and the GCP Cloud
             Billing Catalog API (cloudbilling.googleapis.com/v1) for live
             SKU prices. Falls back to a hardcoded rate table when the API
             is unavailable or a SKU match fails.
Need: Infrastructure decisions made without live pricing data lead to
      unpredictable cloud bills and over/under-provisioned resources.
Motive: Give the human approver (Gate 3) accurate, live cost comparisons
        before infra is provisioned, preventing budget surprises.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from functools import lru_cache

from src.models.cost_models import ArchitectureCostEstimate, ServiceCostItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GCP Cloud Billing Catalog API
# Docs: https://cloud.google.com/billing/docs/reference/rest/v1/services.skus/list
# Requires GCP_API_KEY env var (no billing account needed — public read API).
# ---------------------------------------------------------------------------
_GCP_BILLING_BASE = "https://cloudbilling.googleapis.com/v1"

# GCP service IDs — discover all via GET /v1/services; these are stable public IDs.
_SERVICE_IDS: dict[str, str] = {
    "compute":   "6F81-5844-456A",  # Compute Engine
    "cloud_run": "152E-C115-5142",  # Cloud Run
    "cloud_sql": "9662-B51E-5089",  # Cloud SQL
    "gcs":       "95FF-2EF5-5EA1",  # Cloud Storage
    "bigquery":  "24E6-581D-38E5",  # BigQuery
    "gke":       "9BF3-C3A6-5489",  # Google Kubernetes Engine
    "pubsub":    "A1E8-BE35-7EEA",  # Cloud Pub/Sub
    "lb":        "34A2-4EB4-49D2",  # Cloud Load Balancing
    "redis":     "BAB8-F57B-B28F",  # Memorystore for Redis
}

# (service_key, description_substr_lower, usage_unit, per_month_multiplier, rate_key)
# per_month_multiplier converts the SKU unit to monthly USD:
#   730.0     = hours/month  (hourly SKUs)
#   2_592_000 = seconds/month (per-second SKUs, e.g. Cloud Run)
#   1.0       = already monthly (GiBy.mo SKUs)
_SKU_TARGETS: list[tuple[str, str, str, float, str]] = [
    ("compute",   "n2 instance core",       "h",       730.0,         "gce_vcpu"),
    ("compute",   "n2 instance ram",        "h",       730.0,         "gce_ram_gb"),
    ("compute",   "ssd backed pd capacity", "GiBy.mo", 1.0,           "gce_disk_gb"),
    ("cloud_run", "cpu allocation time",    "s",       2_592_000.0,   "cloud_run_vcpu"),
    ("cloud_run", "memory allocation time", "s",       2_592_000.0,   "cloud_run_ram_gb"),
    ("cloud_run", "requests",               "1",       1.0,           "cloud_run_req_million"),
    ("cloud_sql", "db n1 standard 2",       "h",       730.0,         "cloud_sql_standard_2"),
    ("cloud_sql", "ssd storage",            "GiBy.mo", 1.0,           "cloud_sql_storage_gb"),
    ("gcs",       "standard storage",       "GiBy.mo", 1.0,           "gcs_standard_gb"),
    ("bigquery",  "active storage",         "GiBy.mo", 1.0,           "bq_storage_gb"),
    ("bigquery",  "analysis",               "TiBy",    1.0,           "bq_query_tb"),
    ("gke",       "autopilot pod vcpu",     "h",       730.0,         "gke_vcpu"),
    ("gke",       "autopilot pod memory",   "h",       730.0,         "gke_ram_gb"),
    ("pubsub",    "message delivery",       "GiBy",    1.0,           "pubsub_msg_million"),
    ("lb",        "forwarding rule charge", "h",       730.0,         "lb_forwarding_rule"),
    ("redis",     "redis capacity",         "GiBy.mo", 1.0,           "memorystore_redis_gb"),
]

# ---------------------------------------------------------------------------
# Hardcoded fallback rates (GCP public list pricing, us-central1, 2026-08)
# These are used when GCP_API_KEY is unset OR a specific SKU fails to match.
# ---------------------------------------------------------------------------
_RATES: dict[str, float] = {
    "gce_vcpu": 12.41,
    "gce_ram_gb": 1.66,
    "gce_disk_gb": 0.04,
    "gke_cluster_mgmt": 73.0,
    "gke_vcpu": 32.45,
    "gke_ram_gb": 3.58,
    "cloud_run_vcpu": 2.49,
    "cloud_run_ram_gb": 0.27,
    "cloud_run_req_million": 0.40,
    "cloud_sql_standard_1": 46.03,
    "cloud_sql_standard_2": 92.07,
    "cloud_sql_standard_4": 184.14,
    "cloud_sql_storage_gb": 0.17,
    "gcs_standard_gb": 0.020,
    "gcs_nearline_gb": 0.010,
    "pubsub_msg_million": 0.04,
    "bq_storage_gb": 0.020,
    "bq_query_tb": 5.00,
    "lb_forwarding_rule": 18.26,
    "lb_data_gb": 0.008,
    "memorystore_redis_gb": 0.049,
    "vertex_gemini_input_mtok": 3.50,
    "vertex_gemini_output_mtok": 10.50,
}


def _fetch_sku_page(service_id: str, api_key: str, page_token: str = "") -> dict:
    """Fetch one paginated page of SKUs from the GCP Billing Catalog API."""
    params: dict[str, str] = {
        "key": api_key,
        "currencyCode": "USD",
        "pageSize": "500",
    }
    if page_token:
        params["pageToken"] = page_token
    url = (
        f"{_GCP_BILLING_BASE}/services/{service_id}/skus"
        f"?{urllib.parse.urlencode(params)}"
    )
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


@lru_cache(maxsize=32)
def _fetch_live_rates(api_key: str, region: str) -> dict[str, float]:
    """Fetch live SKU unit prices from the GCP Cloud Billing Catalog API.

    Returns a rates dict in the same format as _RATES.
    LRU-cached per (api_key, region) — one round of API calls per process lifetime.
    Any SKU that fails to match falls through to the hardcoded _RATES value.

    API: https://cloud.google.com/billing/docs/reference/rest/v1/services.skus/list
    """
    live = dict(_RATES)

    by_service: dict[str, list[tuple]] = {}
    for svc_key, desc, uunit, mult, rkey in _SKU_TARGETS:
        by_service.setdefault(svc_key, []).append((desc, uunit, mult, rkey))

    for svc_key, targets in by_service.items():
        service_id = _SERVICE_IDS.get(svc_key)
        if not service_id:
            continue
        try:
            page_token = ""
            while True:
                page = _fetch_sku_page(service_id, api_key, page_token)
                for sku in page.get("skus", []):
                    desc_lower = sku.get("description", "").lower()
                    # Only on-demand pricing; skip committed-use / spot / preemptible
                    usage_type = sku.get("category", {}).get("usageType", "").lower()
                    if usage_type not in ("ondemand", ""):
                        continue
                    # Region filter: accept if our region is in the list, or no list
                    svc_regions = sku.get("serviceRegions", [])
                    if svc_regions and region not in svc_regions:
                        continue
                    for target_desc, uunit, mult, rkey in targets:
                        if target_desc not in desc_lower:
                            continue
                        pricing_info = sku.get("pricingInfo", [{}])
                        expr = pricing_info[0].get("pricingExpression", {})
                        if expr.get("usageUnit", "") != uunit:
                            continue
                        tiers = expr.get("tieredRates", [])
                        if not tiers:
                            continue
                        up = tiers[0].get("unitPrice", {})
                        # Price = whole USD units + fractional nanos (1 nanos = 1e-9 USD)
                        price = int(up.get("units", 0)) + int(up.get("nanos", 0)) / 1_000_000_000
                        if price > 0:
                            live[rkey] = round(price * mult, 6)
                page_token = page.get("nextPageToken", "")
                if not page_token:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Billing API fetch failed for service %s (%s); using fallback rates",
                svc_key, exc,
            )
    return dict(live)


class CostScalingAgent:
    """Estimates GCP costs from a free-text architecture description."""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        gcp_api_key: str | None = None,
    ) -> None:
        self._gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self._gcp_api_key = gcp_api_key or os.environ.get("GCP_API_KEY")
        self._gemini = None
        if self._gemini_api_key:
            try:
                from google import genai
                self._gemini = genai.Client(api_key=self._gemini_api_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini SDK unavailable (%s); fallback parser active", exc)

    def _get_rates(self, region: str) -> dict[str, float]:
        """Return live Billing API rates if GCP_API_KEY is set, else hardcoded _RATES."""
        if self._gcp_api_key:
            try:
                return _fetch_live_rates(self._gcp_api_key, region)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Live rates unavailable (%s); using hardcoded fallback", exc)
        return dict(_RATES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_from_architecture(
        self, architecture_text: str, region: str = "us-central1"
    ) -> ArchitectureCostEstimate:
        """Parse architecture_text, fetch live prices, return full monthly estimate."""
        parsed = self._gemini_parse(architecture_text)
        rates = self._get_rates(region)
        return self._price_services(parsed, region, rates)

    def compute_cost_savings(self, baseline: dict, target: dict) -> dict:
        """Return savings comparison between two cost dicts with 'monthly_cost_usd' keys."""
        b = float(baseline.get("monthly_cost_usd", 0))
        t = float(target.get("monthly_cost_usd", 0))
        savings = b - t
        pct = (savings / b * 100) if b > 0 else 0.0
        return {
            "baseline_monthly_cost_usd": round(b, 2),
            "target_monthly_cost_usd": round(t, 2),
            "monthly_savings_usd": round(savings, 2),
            "savings_pct": round(pct, 1),
        }

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _gemini_parse(self, architecture_text: str) -> list[dict]:
        """Return a list of service spec dicts. Falls back on any Gemini failure."""
        if not self._gemini:
            return self._fallback_parse(architecture_text)
        prompt = (
            "Parse this GCP architecture description into a JSON array of services.\n"
            "For each service include: type, count, and numeric specs.\n\n"
            "Supported types: gce, gke, cloud_run, cloud_sql, gcs, pubsub, bigquery, "
            "load_balancer, memorystore, vertex_ai\n\n"
            "Example output:\n"
            "[\n"
            '  {"type":"cloud_run","count":2,"cpu_vcpu":1,"ram_gb":0.5,"requests_per_month":500000},\n'
            '  {"type":"cloud_sql","tier":"db-n1-standard-2","count":1,"storage_gb":100},\n'
            '  {"type":"gcs","count":1,"storage_gb":250}\n'
            "]\n\n"
            "Return ONLY the JSON array — no markdown, no explanation.\n\n"
            f"Architecture:\n{architecture_text}"
        )
        try:
            resp = self._gemini.models.generate_content(
                model="gemini-2.5-pro", contents=prompt
            )
            raw = (resp.text or "").strip()
            # Strip accidental markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw, flags=re.IGNORECASE)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini parse failed (%s); using fallback", exc)
        return self._fallback_parse(architecture_text)

    def _fallback_parse(self, text: str) -> list[dict]:
        """Keyword-based parser used when Gemini is unavailable."""
        lower = text.lower()
        services: list[dict] = []

        def _count(keywords: list[str]) -> int:
            for kw in keywords:
                m = re.search(r"(\d+)\s+" + re.escape(kw), lower)
                if m:
                    return int(m.group(1))
            return 1

        def _num(pattern: str, default: float) -> float:
            m = re.search(pattern, lower)
            return float(m.group(1).replace(",", "")) if m else default

        if "cloud run" in lower:
            services.append({
                "type": "cloud_run",
                "count": _count(["cloud run"]),
                "cpu_vcpu": _num(r"(\d+)\s*vcpu", 1.0),
                "ram_gb": _num(r"(\d+(?:\.\d+)?)\s*gb\s*ram", 0.5),
                "requests_per_month": int(_num(r"(\d+(?:,\d+)*)\s*req", 100_000)),
            })
        if any(k in lower for k in ("gce", "compute engine", " vm ")):
            services.append({
                "type": "gce",
                "count": _count(["gce", "vm", "instance"]),
                "cpu_vcpu": _num(r"(\d+)\s*vcpu", 2.0),
                "ram_gb": _num(r"(\d+)\s*gb\s*ram", 8.0),
                "disk_gb": _num(r"(\d+)\s*gb\s*disk", 50.0),
            })
        if "gke" in lower or "kubernetes" in lower:
            services.append({
                "type": "gke",
                "count": _count(["gke", "node"]),
                "cpu_vcpu": _num(r"(\d+)\s*vcpu", 2.0),
                "ram_gb": _num(r"(\d+)\s*gb\s*ram", 8.0),
            })
        if "cloud sql" in lower or "postgres" in lower or "mysql" in lower:
            services.append({
                "type": "cloud_sql",
                "tier": "db-n1-standard-2",
                "count": _count(["cloud sql", "database", "db"]),
                "storage_gb": _num(r"(\d+)\s*gb\s*storage", 100.0),
            })
        if "gcs" in lower or "cloud storage" in lower or "bucket" in lower:
            services.append({
                "type": "gcs",
                "count": 1,
                "storage_gb": _num(r"(\d+)\s*gb", 100.0),
            })
        if "pub/sub" in lower or "pubsub" in lower:
            services.append({
                "type": "pubsub",
                "count": 1,
                "messages_per_month": int(_num(r"(\d+(?:,\d+)*)\s*msg", 1_000_000)),
            })
        if "bigquery" in lower or "big query" in lower:
            services.append({
                "type": "bigquery",
                "count": 1,
                "storage_gb": _num(r"(\d+)\s*tb", 1.0) * 1024,
                "query_tb_per_month": _num(r"(\d+(?:\.\d+)?)\s*tb.*quer", 1.0),
            })
        if "load balancer" in lower or "load balancing" in lower:
            services.append({"type": "load_balancer", "count": 1, "rules": 1, "data_gb": 100.0})
        if "memorystore" in lower or "redis" in lower:
            services.append({
                "type": "memorystore",
                "count": 1,
                "ram_gb": _num(r"(\d+)\s*gb", 1.0),
            })
        if "vertex" in lower or "gemini" in lower:
            services.append({
                "type": "vertex_ai",
                "count": 1,
                "input_mtokens_per_month": _num(r"(\d+)\s*m.*token", 1.0),
                "output_mtokens_per_month": _num(r"(\d+)\s*m.*output", 0.5),
            })

        if not services:
            # Absolute fallback: assume a tiny GCE instance
            services.append({"type": "gce", "count": 1, "cpu_vcpu": 2.0,
                              "ram_gb": 8.0, "disk_gb": 50.0})
        return services

    # ------------------------------------------------------------------
    # Pricing engine
    # ------------------------------------------------------------------

    def _price_services(
        self, parsed: list[dict], region: str, rates: dict[str, float] | None = None
    ) -> ArchitectureCostEstimate:
        """Convert a list of parsed service dicts into a costed breakdown."""
        if rates is None:
            rates = self._get_rates(region)
        items: list[ServiceCostItem] = []
        for svc in parsed:
            svc_type = svc.get("type", "")
            count = float(svc.get("count", 1))
            pricer = _PRICERS.get(svc_type)
            if pricer:
                items.extend(pricer(svc, count, rates))

        total = round(sum(i.monthly_cost_usd for i in items), 2)
        return ArchitectureCostEstimate(
            services=items,
            total_monthly_cost_usd=total,
            region=region,
            parsed_services_count=len(parsed),
        )


# ---------------------------------------------------------------------------
# Per-service pricer functions — each returns list[ServiceCostItem]
# rates dict is passed in so live prices are used when available
# ---------------------------------------------------------------------------

def _price_gce(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    cpu = float(svc.get("cpu_vcpu", 2)) * count
    ram = float(svc.get("ram_gb", 8)) * count
    disk = float(svc.get("disk_gb", 50)) * count
    return [
        ServiceCostItem(service_name="GCE", sku_description=f"{cpu:.0f} vCPU",
                        quantity=cpu, unit="vCPU/month",
                        unit_price_usd=rates["gce_vcpu"],
                        monthly_cost_usd=round(cpu * rates["gce_vcpu"], 2)),
        ServiceCostItem(service_name="GCE", sku_description=f"{ram:.0f} GB RAM",
                        quantity=ram, unit="GB/month",
                        unit_price_usd=rates["gce_ram_gb"],
                        monthly_cost_usd=round(ram * rates["gce_ram_gb"], 2)),
        ServiceCostItem(service_name="GCE", sku_description=f"{disk:.0f} GB SSD disk",
                        quantity=disk, unit="GB/month",
                        unit_price_usd=rates["gce_disk_gb"],
                        monthly_cost_usd=round(disk * rates["gce_disk_gb"], 2)),
    ]


def _price_gke(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    cpu = float(svc.get("cpu_vcpu", 2)) * count
    ram = float(svc.get("ram_gb", 8)) * count
    return [
        ServiceCostItem(service_name="GKE", sku_description="Autopilot cluster management",
                        quantity=1.0, unit="cluster/month",
                        unit_price_usd=rates["gke_cluster_mgmt"],
                        monthly_cost_usd=rates["gke_cluster_mgmt"]),
        ServiceCostItem(service_name="GKE", sku_description=f"{cpu:.0f} vCPU (Autopilot)",
                        quantity=cpu, unit="vCPU/month",
                        unit_price_usd=rates["gke_vcpu"],
                        monthly_cost_usd=round(cpu * rates["gke_vcpu"], 2)),
        ServiceCostItem(service_name="GKE", sku_description=f"{ram:.0f} GB RAM (Autopilot)",
                        quantity=ram, unit="GB/month",
                        unit_price_usd=rates["gke_ram_gb"],
                        monthly_cost_usd=round(ram * rates["gke_ram_gb"], 2)),
    ]


def _price_cloud_run(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    cpu = float(svc.get("cpu_vcpu", 1)) * count
    ram = float(svc.get("ram_gb", 0.5)) * count
    reqs_m = float(svc.get("requests_per_month", 100_000)) * count / 1_000_000
    billable_reqs_m = max(0.0, reqs_m - 2.0)  # 2M requests free per month
    items = [
        ServiceCostItem(service_name="Cloud Run",
                        sku_description=f"{cpu:.1f} vCPU (20% duty cycle est.)",
                        quantity=cpu, unit="vCPU/month",
                        unit_price_usd=rates["cloud_run_vcpu"],
                        monthly_cost_usd=round(cpu * rates["cloud_run_vcpu"], 2)),
        ServiceCostItem(service_name="Cloud Run",
                        sku_description=f"{ram:.2f} GB RAM (20% duty cycle est.)",
                        quantity=ram, unit="GB/month",
                        unit_price_usd=rates["cloud_run_ram_gb"],
                        monthly_cost_usd=round(ram * rates["cloud_run_ram_gb"], 2)),
    ]
    if billable_reqs_m > 0:
        items.append(ServiceCostItem(
            service_name="Cloud Run",
            sku_description=f"{reqs_m:.2f}M requests (2M free)",
            quantity=billable_reqs_m, unit="million requests",
            unit_price_usd=rates["cloud_run_req_million"],
            monthly_cost_usd=round(billable_reqs_m * rates["cloud_run_req_million"], 2),
        ))
    return items


def _price_cloud_sql(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    tier = svc.get("tier", "db-n1-standard-2")
    storage = float(svc.get("storage_gb", 100)) * count
    tier_key = {
        "db-n1-standard-1": "cloud_sql_standard_1",
        "db-n1-standard-2": "cloud_sql_standard_2",
        "db-n1-standard-4": "cloud_sql_standard_4",
    }.get(tier, "cloud_sql_standard_2")
    instance_cost = rates[tier_key] * count
    return [
        ServiceCostItem(service_name="Cloud SQL",
                        sku_description=f"{tier} x {count:.0f}",
                        quantity=count, unit="instance/month",
                        unit_price_usd=rates[tier_key],
                        monthly_cost_usd=round(instance_cost, 2)),
        ServiceCostItem(service_name="Cloud SQL",
                        sku_description=f"{storage:.0f} GB SSD storage",
                        quantity=storage, unit="GB/month",
                        unit_price_usd=rates["cloud_sql_storage_gb"],
                        monthly_cost_usd=round(storage * rates["cloud_sql_storage_gb"], 2)),
    ]


def _price_gcs(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    storage = float(svc.get("storage_gb", 100)) * count
    return [ServiceCostItem(
        service_name="GCS", sku_description=f"{storage:.0f} GB Standard",
        quantity=storage, unit="GB/month",
        unit_price_usd=rates["gcs_standard_gb"],
        monthly_cost_usd=round(storage * rates["gcs_standard_gb"], 2),
    )]


def _price_pubsub(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    msgs_m = float(svc.get("messages_per_month", 1_000_000)) * count / 1_000_000
    billable = max(0.0, msgs_m - 10.0)  # first 10M messages free
    cost = round(billable * rates["pubsub_msg_million"], 2)
    return [ServiceCostItem(
        service_name="Pub/Sub", sku_description=f"{msgs_m:.1f}M messages (10M free)",
        quantity=billable, unit="million messages",
        unit_price_usd=rates["pubsub_msg_million"],
        monthly_cost_usd=cost,
    )]


def _price_bigquery(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    storage_gb = float(svc.get("storage_gb", 100)) * count
    query_tb = float(svc.get("query_tb_per_month", 1.0)) * count
    return [
        ServiceCostItem(service_name="BigQuery",
                        sku_description=f"{storage_gb:.0f} GB active storage",
                        quantity=storage_gb, unit="GB/month",
                        unit_price_usd=rates["bq_storage_gb"],
                        monthly_cost_usd=round(storage_gb * rates["bq_storage_gb"], 2)),
        ServiceCostItem(service_name="BigQuery",
                        sku_description=f"{query_tb:.1f} TB queries (on-demand)",
                        quantity=query_tb, unit="TB/month",
                        unit_price_usd=rates["bq_query_tb"],
                        monthly_cost_usd=round(query_tb * rates["bq_query_tb"], 2)),
    ]


def _price_load_balancer(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    rules = float(svc.get("rules", 1)) * count
    data_gb = float(svc.get("data_gb", 100)) * count
    return [
        ServiceCostItem(service_name="Load Balancer",
                        sku_description=f"{rules:.0f} forwarding rule(s)",
                        quantity=rules, unit="rule/month",
                        unit_price_usd=rates["lb_forwarding_rule"],
                        monthly_cost_usd=round(rules * rates["lb_forwarding_rule"], 2)),
        ServiceCostItem(service_name="Load Balancer",
                        sku_description=f"{data_gb:.0f} GB data processed",
                        quantity=data_gb, unit="GB/month",
                        unit_price_usd=rates["lb_data_gb"],
                        monthly_cost_usd=round(data_gb * rates["lb_data_gb"], 2)),
    ]


def _price_memorystore(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    ram = float(svc.get("ram_gb", 1)) * count
    return [ServiceCostItem(
        service_name="Memorystore (Redis)", sku_description=f"{ram:.1f} GB",
        quantity=ram, unit="GB/month",
        unit_price_usd=rates["memorystore_redis_gb"],
        monthly_cost_usd=round(ram * rates["memorystore_redis_gb"], 2),
    )]


def _price_vertex_ai(svc: dict, count: float, rates: dict) -> list[ServiceCostItem]:
    inp = float(svc.get("input_mtokens_per_month", 1.0)) * count
    out = float(svc.get("output_mtokens_per_month", 0.5)) * count
    return [
        ServiceCostItem(service_name="Vertex AI (Gemini Pro)",
                        sku_description=f"{inp:.1f}M input tokens",
                        quantity=inp, unit="million tokens/month",
                        unit_price_usd=rates["vertex_gemini_input_mtok"],
                        monthly_cost_usd=round(inp * rates["vertex_gemini_input_mtok"], 2)),
        ServiceCostItem(service_name="Vertex AI (Gemini Pro)",
                        sku_description=f"{out:.1f}M output tokens",
                        quantity=out, unit="million tokens/month",
                        unit_price_usd=rates["vertex_gemini_output_mtok"],
                        monthly_cost_usd=round(out * rates["vertex_gemini_output_mtok"], 2)),
    ]


_PRICERS = {
    "gce": _price_gce,
    "gke": _price_gke,
    "cloud_run": _price_cloud_run,
    "cloud_sql": _price_cloud_sql,
    "gcs": _price_gcs,
    "pubsub": _price_pubsub,
    "bigquery": _price_bigquery,
    "load_balancer": _price_load_balancer,
    "memorystore": _price_memorystore,
    "vertex_ai": _price_vertex_ai,
}
