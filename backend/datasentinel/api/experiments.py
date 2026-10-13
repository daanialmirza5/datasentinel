from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datasentinel.api.deps import get_db, get_settings_dep
from datasentinel.config import Settings
from datasentinel.lab.faults import catalogue
from datasentinel.models import Dataset, DatasetVersion, Experiment
from datasentinel.services import datasets as ds
from datasentinel.services import experiments as svc

router = APIRouter(prefix="/experiments", tags=["fault lab"])

FaultName = Literal[
    "missing_values",
    "duplicate_records",
    "numeric_outliers",
    "schema_type_change",
    "column_removal",
    "unexpected_categories",
    "row_count_reduction",
    "timestamp_corruption",
    "referential_integrity",
    "distribution_shift",
]


class ExperimentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=40)
    version_id: str | None = Field(default=None, max_length=40)
    fault_type: FaultName
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


class RegenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


def experiment_out(session: Session, exp: Experiment, full: bool = True) -> dict[str, Any]:
    dataset = session.get(Dataset, exp.dataset_id)
    base = session.get(DatasetVersion, exp.base_version_id)
    out: dict[str, Any] = {
        "id": exp.id,
        "dataset_id": exp.dataset_id,
        "dataset_name": dataset.name if dataset else None,
        "base_version_id": exp.base_version_id,
        "base_version_number": base.version_number if base else None,
        "lab_dataset_id": exp.lab_dataset_id,
        "result_version_id": exp.result_version_id,
        "fault_type": exp.fault_type,
        "params": exp.params,
        "seed": exp.seed,
        "status": exp.status,
        "error": exp.error,
        "duration_ms": exp.duration_ms,
        "created_at": exp.created_at.isoformat(),
        "expires_at": exp.expires_at.isoformat() if exp.expires_at else None,
        "outcome": exp.evaluation.get("outcome"),
        "detected": exp.evaluation.get("detected"),
        "counts": exp.evaluation.get("counts"),
    }
    if full:
        out.update({"ground_truth": exp.ground_truth, "detection": exp.detection, "evaluation": exp.evaluation})
    return out


@router.get("/fault-types")
def fault_types(
    dataset_id: str | None = None,
    version_id: str | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Available faults with parameter schemas; with ``dataset_id``, also the columns each fault can target."""
    ctx = None
    if dataset_id:
        dataset = ds.get_dataset(session, dataset_id)
        ctx = svc.fault_context(session, settings, ds.resolve_version(session, dataset, version_id), seed=0)
    return {"fault_types": catalogue(ctx)}


@router.post("", status_code=201)
def create(
    body: ExperimentIn, session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, Any]:
    """Inject a fault into a copy of a version, run the same detection pipeline, and score it against ground truth."""
    experiment = svc.create_experiment(
        session,
        settings,
        dataset_id=body.dataset_id,
        fault_type=body.fault_type,
        params=body.params,
        seed=body.seed,
        version_id=body.version_id,
    )
    return experiment_out(session, experiment)


@router.get("")
def list_experiments(
    dataset_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(Experiment)
    if dataset_id:
        query = query.where(Experiment.dataset_id == dataset_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(Experiment.created_at.desc()).limit(limit).offset(offset))
    return {
        "items": [experiment_out(session, e, full=False) for e in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{experiment_id}")
def get(experiment_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    return experiment_out(session, svc.get_experiment(session, experiment_id))


@router.post("/{experiment_id}/regenerate")
def regenerate(
    experiment_id: str,
    body: RegenerateIn | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Discard the generated data and re-run. Same seed → byte-identical data; new seed → new sample."""
    experiment = svc.regenerate(
        session, settings, svc.get_experiment(session, experiment_id), seed=(body.seed if body else None)
    )
    return experiment_out(session, experiment)


@router.delete("/{experiment_id}")
def reset(
    experiment_id: str, session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, Any]:
    """Delete the experiment and its generated lab data. The original dataset is untouched."""
    svc.delete_experiment(session, settings, svc.get_experiment(session, experiment_id))
    return {"deleted": True, "experiment_id": experiment_id}
