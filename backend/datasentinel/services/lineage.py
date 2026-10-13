"""Lineage graph assembly and per-asset health.

Health states are derived only from stored evidence for the asset's *current* dataset version:

* ``failing``     — at least one quality rule failed, or a breaking schema change was detected
                    (column removed, or a high/critical type change). These are deterministic facts
                    about the data, not statistical judgements.
* ``anomalous``   — no failed rules, but drift detection raised medium-or-higher statistical signals.
                    A signal is a reason to investigate, not proof of corruption.
* ``passing``     — rules ran and passed and no medium+ signals exist.
* ``unvalidated`` — a dataset with no validation run and no drift comparison.
* ``no_checks``   — non-dataset assets (sources, transformations, reports, models) carry no checks
                    of their own; their risk comes only from upstream.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.detection.signals import SEVERITY_RANK
from datasentinel.lineage.graph import Graph, find_cycles, layered_layout
from datasentinel.models import Dataset, LineageAsset, LineageEdge
from datasentinel.services.datasets import current_version
from datasentinel.services.drift import latest_drift
from datasentinel.services.validation import latest_run

ASSET_KINDS = ("source", "dataset", "transformation", "report", "model")
BREAKING_CATEGORIES = {"column_removed"}


def _breaking(signal: dict[str, Any]) -> bool:
    if signal["category"] in BREAKING_CATEGORIES:
        return True
    return signal["category"] == "type_change" and SEVERITY_RANK[signal["severity"]] >= SEVERITY_RANK["high"]


def dataset_health(session: Session, dataset: Dataset) -> dict[str, Any]:
    version = current_version(session, dataset)
    if version is None:
        return {"state": "unvalidated", "reason": "Dataset has no versions."}
    run = latest_run(session, dataset.id, version.id)
    drift = latest_drift(session, dataset.id, version.id)
    failed_rules = []
    if run is not None:
        failed_rules = [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "rule_type": r.rule_type,
                "column": r.column_name,
                "severity": r.severity,
                "violation_count": r.violation_count,
                "message": r.message,
                "recommendation": r.recommendation,
            }
            for r in run.results
            if r.status == "failed"
        ]
    signals = drift.result.get("signals", []) if drift else []
    breaking = [s for s in signals if _breaking(s)]
    notable = [
        s for s in signals if SEVERITY_RANK.get(s["severity"], 0) >= SEVERITY_RANK["medium"] and not _breaking(s)
    ]
    if failed_rules or breaking:
        state = "failing"
    elif notable:
        state = "anomalous"
    elif run is not None or drift is not None:
        state = "passing"
    else:
        state = "unvalidated"
    return {
        "state": state,
        "dataset_id": dataset.id,
        "version_id": version.id,
        "version_number": version.version_number,
        "validation_run_id": run.id if run else None,
        "validation_summary": run.summary if run else None,
        "drift_result_id": drift.id if drift else None,
        "base_version_id": drift.base_version_id if drift else None,
        "failed_rules": failed_rules,
        "breaking_changes": breaking,
        "anomaly_signals": notable,
        "schema_changes": drift.result.get("schema_changes", []) if drift else [],
    }


def asset_health(session: Session, asset: LineageAsset) -> dict[str, Any]:
    if asset.dataset_id:
        dataset = session.get(Dataset, asset.dataset_id)
        if dataset is not None:
            return dataset_health(session, dataset)
    return {"state": "no_checks", "reason": f"{asset.kind.capitalize()} assets have no checks of their own."}


def build_graph(session: Session) -> Graph:
    graph = Graph()
    for asset in session.scalars(select(LineageAsset).order_by(LineageAsset.name)):
        graph.add_node(asset.id, name=asset.name, kind=asset.kind, dataset_id=asset.dataset_id)
    for edge in session.scalars(select(LineageEdge)):
        if edge.source_id in graph.nodes and edge.target_id in graph.nodes:
            graph.add_edge(edge.source_id, edge.target_id, edge.description)
    return graph


def asset_dict(asset: LineageAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        "description": asset.description,
        "owner": asset.owner,
        "dataset_id": asset.dataset_id,
        "created_at": asset.created_at.isoformat(),
    }


def overview(session: Session, include_lab: bool = False) -> dict[str, Any]:
    assets = list(session.scalars(select(LineageAsset).order_by(LineageAsset.name)))
    if not include_lab:
        lab_ids = set(session.scalars(select(Dataset.id).where(Dataset.kind == "lab")))
        assets = [a for a in assets if a.dataset_id not in lab_ids]
    keep = {a.id for a in assets}
    sub = Graph()
    for asset in assets:
        sub.add_node(asset.id, name=asset.name, kind=asset.kind, dataset_id=asset.dataset_id)
    edges = [e for e in session.scalars(select(LineageEdge)) if e.source_id in keep and e.target_id in keep]
    for edge in edges:
        sub.add_edge(edge.source_id, edge.target_id, edge.description)
    positions = layered_layout(sub)
    nodes = []
    for asset in assets:
        health = asset_health(session, asset)
        nodes.append(
            {
                **asset_dict(asset),
                "position": positions.get(asset.id, {"x": 0, "y": 0}),
                "health": {
                    "state": health["state"],
                    "version_number": health.get("version_number"),
                    "failed_rule_count": len(health.get("failed_rules", [])),
                    "signal_count": len(health.get("anomaly_signals", [])) + len(health.get("breaking_changes", [])),
                },
                "upstream_count": len(sub.inc[asset.id]),
                "downstream_count": len(sub.out[asset.id]),
            }
        )
    return {
        "nodes": nodes,
        "edges": [
            {"id": e.id, "source": e.source_id, "target": e.target_id, "description": e.description} for e in edges
        ],
        "cycles": find_cycles(sub),
    }
