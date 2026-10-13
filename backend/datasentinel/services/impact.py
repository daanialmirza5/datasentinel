"""Downstream impact propagation over the declared lineage graph.

Classification of each downstream asset (relative to the origin asset):

* ``confirmed_failure`` — the asset's *own* current version failed rules or has breaking schema
  changes (independent evidence, whatever the origin's state).
* ``suspected_impact``  — the origin is failing and the asset reads it directly (distance 1), or
  the asset's own data shows statistical anomalies.
* ``unverified_risk``   — the asset is further downstream of a failing or anomalous origin and
  has no evidence of its own. Dependence alone is not proof of corruption.
* ``no_known_impact``   — the origin shows no failure; the asset is listed only to show the
  dependency footprint.

Only *declared* dependencies are followed; nothing is inferred from names or data.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.lineage.graph import downstream
from datasentinel.models import Dataset, DatasetVersion, LineageAsset, QualityRule
from datasentinel.recommendations import build_recommendations
from datasentinel.services.lineage import asset_dict, asset_health, build_graph
from datasentinel.services.validation import latest_run

CLASS_RANK = {"no_known_impact": 0, "unverified_risk": 1, "suspected_impact": 2, "confirmed_failure": 3}


def restore_candidate(session: Session, health: dict[str, Any]) -> dict[str, Any] | None:
    """Newest earlier active version whose latest validation passed with no failures."""
    dataset_id, current_number = health.get("dataset_id"), health.get("version_number")
    if not dataset_id or current_number is None:
        return None
    earlier = session.scalars(
        select(DatasetVersion)
        .where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version_number < current_number,
            DatasetVersion.status == "active",
        )
        .order_by(DatasetVersion.version_number.desc())
    )
    for version in earlier:
        run = latest_run(session, dataset_id, version.id)
        if (
            run is not None
            and run.summary.get("failed", 0) == 0
            and run.summary.get("error", 0) == 0
            and run.summary.get("total", 0) > 0
        ):
            return {
                "version_id": version.id,
                "version_number": version.version_number,
                "evidence": f"passed all {run.summary['total']} enabled rules on {run.started_at.date().isoformat()}",
            }
    return None


def _existing_rules(session: Session, dataset_id: str | None) -> set[tuple[str | None, str]]:
    if not dataset_id:
        return set()
    return {
        (r.column_name, r.rule_type)
        for r in session.scalars(select(QualityRule).where(QualityRule.dataset_id == dataset_id))
    }


def _classify(origin_state: str, distance: int, own_state: str) -> str:
    if own_state == "failing":
        return "confirmed_failure"
    if origin_state == "failing" and distance == 1:
        return "suspected_impact"
    if own_state == "anomalous":
        return "suspected_impact"
    if origin_state in ("failing", "anomalous"):
        return "unverified_risk"
    return "no_known_impact"


def impact_analysis(session: Session, asset: LineageAsset) -> dict[str, Any]:
    graph = build_graph(session)
    origin_health = asset_health(session, asset)
    origin_state = origin_health["state"]
    impacted = []
    for node_id, info in downstream(graph, asset.id).items():
        node = session.get(LineageAsset, node_id)
        if node is None:
            continue
        own = asset_health(session, node)
        classification = _classify(origin_state, info["distance"], own["state"])
        path_names = [graph.nodes[p]["name"] for p in info["path"]]
        evidence = [f"Depends on '{asset.name}' via {' → '.join(path_names)}"]
        if own["state"] == "failing":
            evidence += [f"Own rule '{r['rule_name']}' failed" for r in own.get("failed_rules", [])[:3]]
            evidence += [s["title"] for s in own.get("breaking_changes", [])[:3]]
        elif own["state"] == "anomalous":
            evidence += [s["title"] for s in own.get("anomaly_signals", [])[:3]]
        elif own["state"] == "passing":
            evidence.append("Its own latest checks passed; impact is not confirmed.")
        impacted.append(
            {
                **asset_dict(node),
                "distance": info["distance"],
                "path": path_names,
                "path_ids": info["path"],
                "classification": classification,
                "own_state": own["state"],
                "evidence": evidence,
            }
        )
    impacted.sort(key=lambda i: (i["distance"], -CLASS_RANK[i["classification"]], i["name"]))
    counts = dict.fromkeys(CLASS_RANK, 0)
    for item in impacted:
        counts[item["classification"]] += 1

    if origin_state == "failing":
        assessment = (
            f"'{asset.name}' has confirmed failures ({len(origin_health.get('failed_rules', []))} failed rule(s), "
            f"{len(origin_health.get('breaking_changes', []))} breaking schema change(s)). "
            f"{len(impacted)} downstream asset(s) may be affected."
        )
    elif origin_state == "anomalous":
        assessment = (
            f"'{asset.name}' shows statistical anomalies but no failed rules. Downstream assets are at "
            "unverified risk until the anomalies are explained."
        )
    else:
        assessment = (
            f"No failure is currently detected for '{asset.name}' ({origin_state}). The list shows its "
            "dependency footprint only."
        )
    restore = restore_candidate(session, origin_health) if origin_state in ("failing", "anomalous") else None
    return {
        "origin": {**asset_dict(asset), "health": origin_health},
        "origin_state": origin_state,
        "assessment": assessment,
        "direct": [i for i in impacted if i["distance"] == 1],
        "transitive": [i for i in impacted if i["distance"] > 1],
        "impacted": impacted,
        "counts": counts,
        "restore_candidate": restore,
        "recommendations": build_recommendations(
            asset.name, origin_health, impacted, restore, existing_rules=_existing_rules(session, asset.dataset_id)
        ),
    }


def impact_summary(session: Session) -> dict[str, Any]:
    """Union of downstream impact across every failing or anomalous dataset (worst classification wins)."""
    lab_ids = set(session.scalars(select(Dataset.id).where(Dataset.kind == "lab")))
    origins, worst = [], {}
    for asset in session.scalars(select(LineageAsset).where(LineageAsset.dataset_id.is_not(None))):
        if asset.dataset_id in lab_ids:
            continue
        analysis = impact_analysis(session, asset)
        if analysis["origin_state"] not in ("failing", "anomalous"):
            continue
        origins.append(
            {
                "id": asset.id,
                "name": asset.name,
                "state": analysis["origin_state"],
                "impacted": len(analysis["impacted"]),
            }
        )
        for item in analysis["impacted"]:
            current = worst.get(item["id"])
            if current is None or CLASS_RANK[item["classification"]] > CLASS_RANK[current["classification"]]:
                worst[item["id"]] = {
                    "id": item["id"],
                    "name": item["name"],
                    "kind": item["kind"],
                    "classification": item["classification"],
                    "via": asset.name,
                }
    impacted = sorted(worst.values(), key=lambda i: (-CLASS_RANK[i["classification"]], i["name"]))
    counts = dict.fromkeys(CLASS_RANK, 0)
    for item in impacted:
        counts[item["classification"]] += 1
    return {"origins": origins, "impacted": impacted, "counts": counts}
