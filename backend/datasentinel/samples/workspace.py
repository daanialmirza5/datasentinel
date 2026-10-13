"""Loads the bundled demo workspace: sample datasets, quality rules and declared lineage.

Order matters: rules are created after a dataset's first version so that later versions (August,
September orders) are validated and compared on import exactly as user uploads would be.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.errors import ConflictError
from datasentinel.models import Dataset, LineageAsset, LineageEdge, QualityRule
from datasentinel.rules.params import PARAM_MODELS
from datasentinel.samples.generator import DATA_DIR, PLANTED_ISSUES
from datasentinel.services.datasets import import_version
from datasentinel.services.validation import run_validation

SAMPLE_DATASETS: list[dict[str, Any]] = [
    {"name": "customers", "files": ["customers.csv"], "description": "CRM export of customer accounts."},
    {"name": "products", "files": ["products.json"], "description": "Product catalogue (nested JSON, flattened)."},
    {
        "name": "orders",
        "files": ["orders_2026_07.csv", "orders_2026_08.csv", "orders_2026_09.csv"],
        "description": "Monthly order exports from the shop database (July, August, September 2026).",
    },
    {"name": "daily_revenue", "files": ["daily_revenue.csv"], "description": "Daily revenue derived from orders."},
    {
        "name": "sensor_readings",
        "files": ["sensor_readings.jsonl"],
        "description": "Hourly warehouse sensor readings (JSON Lines). Not connected to the revenue pipeline.",
    },
]


def _rules(ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    return {
        "customers": [
            {"name": "customer_id unique", "rule_type": "unique", "column_name": "customer_id", "severity": "high"},
            {
                "name": "email format",
                "rule_type": "pattern",
                "column_name": "email",
                "severity": "medium",
                "params": {"regex": r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}"},
            },
            {
                "name": "country code known",
                "rule_type": "allowed_values",
                "column_name": "country",
                "severity": "low",
                "params": {"values": ["US", "GB", "DE", "FR", "CA", "IN", "AU", "NL"]},
            },
            {
                "name": "signup not in future",
                "rule_type": "timestamp_range",
                "column_name": "signup_date",
                "severity": "medium",
                "params": {"max_future_days": 1},
            },
        ],
        "products": [
            {"name": "product_id unique", "rule_type": "unique", "column_name": "product_id", "severity": "high"},
            {
                "name": "price positive",
                "rule_type": "range",
                "column_name": "price",
                "severity": "high",
                "params": {"min": 0.01},
            },
        ],
        "orders": [
            {"name": "order_id unique", "rule_type": "unique", "column_name": "order_id", "severity": "high"},
            {
                "name": "customer exists",
                "rule_type": "foreign_key",
                "column_name": "customer_id",
                "severity": "high",
                "params": {"reference_dataset_id": ids["customers"], "reference_column": "customer_id"},
            },
            {
                "name": "status values",
                "rule_type": "allowed_values",
                "column_name": "status",
                "severity": "medium",
                "params": {"values": ["placed", "shipped", "delivered", "cancelled", "returned"]},
            },
            {
                "name": "currency values",
                "rule_type": "allowed_values",
                "column_name": "currency",
                "severity": "high",
                "params": {"values": ["USD", "EUR", "GBP"]},
            },
            {
                "name": "amount range",
                "rule_type": "range",
                "column_name": "amount",
                "severity": "high",
                "params": {"min": 0, "max": 10000},
            },
            {
                "name": "quantity range",
                "rule_type": "range",
                "column_name": "quantity",
                "severity": "medium",
                "params": {"min": 1, "max": 100},
            },
            {"name": "discount present", "rule_type": "column_exists", "column_name": "discount", "severity": "high"},
            {
                "name": "ship_country mostly filled",
                "rule_type": "not_null",
                "column_name": "ship_country",
                "severity": "medium",
                "params": {"max_null_pct": 5},
            },
            {
                "name": "shipped after ordered",
                "rule_type": "column_comparison",
                "column_name": "shipped_ts",
                "severity": "medium",
                "params": {"operator": "ge", "other_column": "order_ts"},
            },
            {
                "name": "order_ts not in future",
                "rule_type": "timestamp_range",
                "column_name": "order_ts",
                "severity": "medium",
                "params": {"max_future_days": 1},
            },
            {
                "name": "monthly volume",
                "rule_type": "row_count",
                "column_name": None,
                "severity": "medium",
                "params": {"min": 1000},
            },
        ],
        "daily_revenue": [
            {
                "name": "revenue non-negative",
                "rule_type": "range",
                "column_name": "revenue",
                "severity": "high",
                "params": {"min": 0},
            },
            {
                "name": "full month",
                "rule_type": "row_count",
                "column_name": None,
                "severity": "low",
                "params": {"min": 28},
            },
        ],
        "sensor_readings": [
            {
                "name": "temperature plausible",
                "rule_type": "range",
                "column_name": "temperature_c",
                "severity": "high",
                "params": {"min": -40, "max": 60},
            },
            {
                "name": "known devices",
                "rule_type": "allowed_values",
                "column_name": "device_id",
                "severity": "medium",
                "params": {"values": ["sensor-a", "sensor-b", "sensor-c"]},
            },
        ],
    }


EXTRA_ASSETS = [
    {
        "name": "Shop database export",
        "kind": "source",
        "owner": "platform-team",
        "description": "Nightly export of the order tables.",
    },
    {"name": "CRM", "kind": "source", "owner": "sales-ops", "description": "Customer relationship system."},
    {"name": "Product catalogue API", "kind": "source", "owner": "merchandising", "description": "Catalogue service."},
    {
        "name": "Revenue aggregation job",
        "kind": "transformation",
        "owner": "analytics-eng",
        "description": "Joins orders with customers and products and aggregates revenue per day.",
    },
    {
        "name": "Executive revenue dashboard",
        "kind": "report",
        "owner": "finance",
        "description": "Board-level revenue reporting.",
    },
    {
        "name": "Demand forecast model",
        "kind": "model",
        "owner": "data-science",
        "description": "Forecasts daily order volume.",
    },
    {
        "name": "Churn risk model",
        "kind": "model",
        "owner": "data-science",
        "description": "Scores customers by churn risk.",
    },
]

EDGES = [
    ("Shop database export", "orders", "nightly export"),
    ("CRM", "customers", "daily sync"),
    ("Product catalogue API", "products", "hourly sync"),
    ("orders", "Revenue aggregation job", "input"),
    ("customers", "Revenue aggregation job", "lookup join"),
    ("products", "Revenue aggregation job", "category join"),
    ("Revenue aggregation job", "daily_revenue", "writes"),
    ("daily_revenue", "Executive revenue dashboard", "feeds"),
    ("daily_revenue", "Demand forecast model", "training data"),
    ("customers", "Churn risk model", "features"),
]


def load_demo_workspace(session: Session, settings: Settings) -> dict[str, Any]:
    names = [d["name"] for d in SAMPLE_DATASETS]
    existing = session.scalars(select(Dataset.name).where(Dataset.name.in_(names))).all()
    if existing:
        raise ConflictError(f"Sample datasets already exist: {', '.join(sorted(existing))}. Delete them to reload.")
    ids: dict[str, str] = {}
    rules = None
    versions = 0
    for spec in SAMPLE_DATASETS:
        first, *later = spec["files"]
        content = (DATA_DIR / first).read_bytes()
        version = import_version(
            session,
            settings,
            content=content,
            filename=first,
            dataset_name=spec["name"],
            description=spec["description"],
            origin="sample",
            kind="sample",
        )
        ids[spec["name"]] = version.dataset_id
        versions += 1
        rules = _rules(ids)
        dataset = session.get(Dataset, version.dataset_id)
        for rule in rules.get(spec["name"], []):
            params = PARAM_MODELS[rule["rule_type"]].model_validate(rule.get("params", {})).model_dump(mode="json")
            session.add(
                QualityRule(
                    dataset_id=dataset.id,
                    name=rule["name"],
                    rule_type=rule["rule_type"],
                    column_name=rule["column_name"],
                    params=params,
                    severity=rule["severity"],
                )
            )
        session.flush()
        run_validation(session, settings, dataset, version, trigger="import")
        for name in later:
            import_version(
                session,
                settings,
                content=(DATA_DIR / name).read_bytes(),
                filename=name,
                dataset_id=dataset.id,
                origin="sample",
                kind="sample",
            )
            versions += 1

    assets = {a.name: a for a in session.scalars(select(LineageAsset))}
    for spec in EXTRA_ASSETS:
        if spec["name"] not in assets:
            asset = LineageAsset(**spec)
            session.add(asset)
            assets[spec["name"]] = asset
    session.flush()
    for source, target, description in EDGES:
        session.add(LineageEdge(source_id=assets[source].id, target_id=assets[target].id, description=description))
    session.flush()
    return {
        "datasets": len(ids),
        "versions": versions,
        "rules": sum(len(v) for v in (rules or {}).values()),
        "assets": len(EXTRA_ASSETS) + len(ids),
        "edges": len(EDGES),
        "planted_issues": PLANTED_ISSUES,
    }
