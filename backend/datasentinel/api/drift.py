from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.api.deps import get_db, get_settings_dep
from datasentinel.config import Settings
from datasentinel.errors import ValidationFailed
from datasentinel.models import DatasetVersion, DriftResult
from datasentinel.services import datasets as ds
from datasentinel.services.drift import get_or_compute_drift, version_ref

router = APIRouter(tags=["drift"])


@router.get("/datasets/{dataset_id}/drift")
def get_drift(
    dataset_id: str,
    base_version_id: str | None = None,
    candidate_version_id: str | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Compare two versions: schema changes, per-column statistics and explained signals.

    Defaults: the candidate is the current version and the base is the newest active version before it.
    """
    dataset = ds.get_dataset(session, dataset_id)
    candidate = ds.resolve_version(session, dataset, candidate_version_id)
    base = (
        ds.get_version(session, dataset, base_version_id)
        if base_version_id
        else ds.previous_version(session, candidate)
    )
    if base is None:
        return {
            "status": "no_baseline",
            "dataset_id": dataset.id,
            "candidate": version_ref(candidate),
            "message": "Drift needs at least two versions. Import a newer version of this dataset to compare.",
        }
    if base.id == candidate.id:
        raise ValidationFailed("Base and candidate versions must differ")
    stored = get_or_compute_drift(session, settings, base, candidate)
    return {
        "status": "ok",
        "dataset_id": dataset.id,
        "base": version_ref(base),
        "candidate": version_ref(candidate),
        "computed_at": stored.computed_at.isoformat(),
        **stored.result,
    }


@router.get("/datasets/{dataset_id}/drift/history")
def drift_history(dataset_id: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Summaries of every stored comparison for the dataset, newest first."""
    dataset = ds.get_dataset(session, dataset_id)
    rows = session.scalars(
        select(DriftResult).where(DriftResult.dataset_id == dataset.id).order_by(DriftResult.computed_at.desc())
    )
    history = []
    for row in rows:
        base, cand = (
            session.get(DatasetVersion, row.base_version_id),
            session.get(DatasetVersion, row.candidate_version_id),
        )
        history.append(
            {
                "id": row.id,
                "computed_at": row.computed_at.isoformat(),
                "base": version_ref(base) if base else None,
                "candidate": version_ref(cand) if cand else None,
                "summary": row.result.get("summary", {}),
            }
        )
    return history
