from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.api.deps import get_db
from datasentinel.errors import ConflictError, NotFoundError, ValidationFailed
from datasentinel.lineage.graph import downstream, upstream, would_create_cycle
from datasentinel.models import Dataset, LineageAsset, LineageEdge
from datasentinel.services import lineage as svc
from datasentinel.services.datasets import list_versions
from datasentinel.services.impact import impact_analysis, impact_summary

router = APIRouter(prefix="/lineage", tags=["lineage"])

AssetKind = Literal["source", "dataset", "transformation", "report", "model"]


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: AssetKind
    description: str = Field(default="", max_length=2000)
    owner: str = Field(default="", max_length=120)


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: AssetKind | None = None
    description: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=120)


class EdgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=40)
    target_id: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=500)


def _asset(session: Session, asset_id: str) -> LineageAsset:
    asset = session.get(LineageAsset, asset_id)
    if asset is None:
        raise NotFoundError(f"Asset '{asset_id}' not found")
    return asset


def _unique_name(session: Session, name: str, exclude: str | None = None) -> str:
    cleaned = name.strip()
    query = select(LineageAsset).where(LineageAsset.name == cleaned)
    if exclude:
        query = query.where(LineageAsset.id != exclude)
    if session.scalar(query) is not None:
        raise ConflictError(f"An asset named '{cleaned}' already exists")
    return cleaned


@router.get("")
def lineage_graph(include_lab: bool = False, session: Session = Depends(get_db)) -> dict[str, Any]:
    """All assets with health state and a deterministic layered layout, all edges, and any cycles."""
    return svc.overview(session, include_lab=include_lab)


@router.post("/assets", status_code=201)
def create_asset(body: AssetIn, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Declare a non-dataset asset (source system, transformation, report, model).

    Dataset assets are created automatically when a dataset is imported.
    """
    if body.kind == "dataset":
        raise ValidationFailed("Dataset assets are created by importing a dataset; choose another kind.")
    asset = LineageAsset(
        name=_unique_name(session, body.name),
        kind=body.kind,
        description=body.description.strip(),
        owner=body.owner.strip(),
    )
    session.add(asset)
    session.flush()
    return svc.asset_dict(asset)


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: str, body: AssetUpdate, session: Session = Depends(get_db)) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    if body.name is not None:
        asset.name = _unique_name(session, body.name, exclude=asset.id)
    if body.kind is not None:
        if asset.dataset_id and body.kind != "dataset":
            raise ValidationFailed("An asset linked to a dataset must keep kind 'dataset'.")
        if not asset.dataset_id and body.kind == "dataset":
            raise ValidationFailed("Only assets linked to an imported dataset can have kind 'dataset'.")
        asset.kind = body.kind
    if body.description is not None:
        asset.description = body.description.strip()
    if body.owner is not None:
        asset.owner = body.owner.strip()
    session.flush()
    return svc.asset_dict(asset)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    if asset.dataset_id:
        raise ConflictError("This asset represents a dataset; delete the dataset to remove it.")
    session.delete(asset)
    return {"deleted": True, "asset_id": asset_id}


@router.post("/edges", status_code=201)
def create_edge(body: EdgeIn, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Declare that ``source_id`` feeds ``target_id``. Rejected if it would create a cycle."""
    source, target = _asset(session, body.source_id), _asset(session, body.target_id)
    exists = session.scalar(
        select(LineageEdge).where(LineageEdge.source_id == source.id, LineageEdge.target_id == target.id)
    )
    if exists is not None:
        raise ConflictError("This dependency already exists")
    cycle = would_create_cycle(svc.build_graph(session), source.id, target.id)
    if cycle:
        names = {a.id: a.name for a in session.scalars(select(LineageAsset))}
        raise ConflictError(
            "Lineage must be acyclic: this dependency would create the cycle "
            + " → ".join(names.get(n, n) for n in cycle),
            details={"cycle": cycle},
        )
    edge = LineageEdge(source_id=source.id, target_id=target.id, description=body.description.strip())
    session.add(edge)
    session.flush()
    return {"id": edge.id, "source": edge.source_id, "target": edge.target_id, "description": edge.description}


@router.delete("/edges/{edge_id}")
def delete_edge(edge_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    edge = session.get(LineageEdge, edge_id)
    if edge is None:
        raise NotFoundError(f"Edge '{edge_id}' not found")
    session.delete(edge)
    return {"deleted": True, "edge_id": edge_id}


@router.get("/impact/summary")
def impact_overview(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Assets potentially affected by any currently failing or anomalous dataset."""
    return impact_summary(session)


@router.get("/{asset_id}/impact")
def asset_impact(asset_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Direct and transitive downstream impact of an asset, with evidence, classification and recommendations."""
    return impact_analysis(session, _asset(session, asset_id))


@router.get("/{asset_id}")
def asset_details(asset_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    """An asset with its upstream and downstream dependencies, versions, failed rules and schema changes."""
    asset = _asset(session, asset_id)
    graph = svc.build_graph(session)

    def describe(found: dict[str, dict]) -> list[dict[str, Any]]:
        return sorted(
            (
                {
                    "id": node,
                    "name": graph.nodes[node]["name"],
                    "kind": graph.nodes[node]["kind"],
                    "distance": info["distance"],
                    "path": [graph.nodes[p]["name"] for p in info["path"]],
                }
                for node, info in found.items()
            ),
            key=lambda item: (item["distance"], item["name"]),
        )

    versions = []
    if asset.dataset_id and session.get(Dataset, asset.dataset_id) is not None:
        versions = [
            {
                "id": v.id,
                "version_number": v.version_number,
                "row_count": v.row_count,
                "status": v.status,
                "imported_at": v.imported_at.isoformat(),
                "origin": v.origin,
            }
            for v in list_versions(session, asset.dataset_id)
        ]
    return {
        **svc.asset_dict(asset),
        "health": svc.asset_health(session, asset),
        "upstream": describe(upstream(graph, asset.id)),
        "downstream": describe(downstream(graph, asset.id)),
        "versions": versions,
    }
