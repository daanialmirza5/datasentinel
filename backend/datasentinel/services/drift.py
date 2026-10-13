"""Cached version-to-version drift results."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.detection.pipeline import DRIFT_ALGORITHM_VERSION, detect_changes
from datasentinel.models import DatasetVersion, DriftResult
from datasentinel.services.datasets import load_table
from datasentinel.services.profiles import get_or_compute_profile


def version_ref(version: DatasetVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "imported_at": version.imported_at.isoformat(),
        "row_count": version.row_count,
        "status": version.status,
    }


def get_or_compute_drift(
    session: Session, settings: Settings, base: DatasetVersion, candidate: DatasetVersion
) -> DriftResult:
    stored = session.scalar(
        select(DriftResult).where(
            DriftResult.base_version_id == base.id,
            DriftResult.candidate_version_id == candidate.id,
            DriftResult.algorithm_version == DRIFT_ALGORITHM_VERSION,
        )
    )
    if stored is not None:
        return stored
    base_profile, _ = get_or_compute_profile(session, settings, base)
    cand_profile, _ = get_or_compute_profile(session, settings, candidate)
    result = detect_changes(
        load_table(settings, base), load_table(settings, candidate), base_profile.profile, cand_profile.profile
    )
    stored = DriftResult(
        dataset_id=candidate.dataset_id,
        base_version_id=base.id,
        candidate_version_id=candidate.id,
        algorithm_version=DRIFT_ALGORITHM_VERSION,
        result=result,
    )
    session.add(stored)
    session.flush()
    return stored


def latest_drift(session: Session, dataset_id: str, candidate_version_id: str | None = None) -> DriftResult | None:
    query = select(DriftResult).where(
        DriftResult.dataset_id == dataset_id, DriftResult.algorithm_version == DRIFT_ALGORITHM_VERSION
    )
    if candidate_version_id:
        query = query.where(DriftResult.candidate_version_id == candidate_version_id)
    return session.scalars(query.order_by(DriftResult.computed_at.desc()).limit(1)).first()
