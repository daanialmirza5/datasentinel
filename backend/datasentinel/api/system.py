"""Dashboard summary, settings disclosure, sample workspace and maintenance endpoints."""

from __future__ import annotations

import importlib.util
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datasentinel import __version__
from datasentinel.api.deps import get_db, get_settings_dep
from datasentinel.config import Settings
from datasentinel.detection.pipeline import DEFAULT_CONFIG
from datasentinel.detection.signals import SEVERITY_RANK
from datasentinel.models import Dataset, DatasetVersion, Experiment, QualityRule, Report
from datasentinel.samples.generator import PLANTED_ISSUES
from datasentinel.samples.workspace import SAMPLE_DATASETS, load_demo_workspace
from datasentinel.services.datasets import current_version, storage_for
from datasentinel.services.drift import latest_drift
from datasentinel.services.experiments import purge_expired
from datasentinel.services.impact import impact_summary
from datasentinel.services.integrity import check_integrity
from datasentinel.services.validation import latest_run

router = APIRouter(tags=["system"])


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Every number on the dashboard, computed from stored results (nothing is estimated)."""
    datasets = list(session.scalars(select(Dataset).where(Dataset.kind != "lab").order_by(Dataset.name)))
    dataset_ids = [d.id for d in datasets]
    version_count = (
        session.scalar(
            select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id.in_(dataset_ids))
        )
        or 0
    )
    recent = session.execute(
        select(DatasetVersion, Dataset.name)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.kind != "lab")
        .order_by(DatasetVersion.imported_at.desc())
        .limit(8)
    ).all()

    rule_totals = {"passed": 0, "failed": 0, "error": 0, "not_evaluated": 0}
    health_rows, anomalies, schema_changes = [], [], []
    for dataset in datasets:
        version = current_version(session, dataset)
        if version is None:
            continue
        run = latest_run(session, dataset.id, version.id)
        if run:
            for key in rule_totals:
                rule_totals[key] += run.summary.get(key, 0)
        drift = latest_drift(session, dataset.id, version.id)
        signals = [
            s
            for s in (drift.result["signals"] if drift else [])
            if SEVERITY_RANK[s["severity"]] >= SEVERITY_RANK["low"]
        ]
        anomalies += [
            {**s, "dataset_id": dataset.id, "dataset_name": dataset.name, "version_number": version.version_number}
            for s in signals
        ]
        if drift:
            schema_changes += [
                {
                    **c,
                    "dataset_id": dataset.id,
                    "dataset_name": dataset.name,
                    "version_number": version.version_number,
                    "computed_at": drift.computed_at.isoformat(),
                }
                for c in drift.result["schema_changes"]
            ]
        health_rows.append(
            {
                "dataset_id": dataset.id,
                "name": dataset.name,
                "kind": dataset.kind,
                "version_number": version.version_number,
                "row_count": version.row_count,
                "health": run.summary.get("health") if run else "no_rules",
                "failed_rules": run.summary.get("failed", 0) if run else 0,
                "signals": len(signals),
                "imported_at": version.imported_at.isoformat(),
            }
        )
    anomalies.sort(key=lambda s: -SEVERITY_RANK[s["severity"]])
    schema_changes.sort(key=lambda c: -SEVERITY_RANK.get(c["severity"], 0))
    experiments_total = session.scalar(select(func.count()).select_from(Experiment)) or 0
    return {
        "dataset_count": len(datasets),
        "version_count": version_count,
        "rule_count": session.scalar(
            select(func.count())
            .select_from(QualityRule)
            .where(QualityRule.dataset_id.in_(dataset_ids), QualityRule.enabled.is_(True))
        )
        or 0,
        "report_count": session.scalar(select(func.count()).select_from(Report)) or 0,
        "experiment_count": experiments_total,
        "recent_imports": [
            {
                "dataset_id": v.dataset_id,
                "dataset_name": name,
                "version_id": v.id,
                "version_number": v.version_number,
                "row_count": v.row_count,
                "origin": v.origin,
                "rejected_row_count": v.rejected_row_count,
                "imported_at": v.imported_at.isoformat(),
                "status": v.status,
            }
            for v, name in recent
        ],
        "rule_status": {**rule_totals, "datasets_failing": sum(1 for h in health_rows if h["health"] == "failing")},
        "active_anomalies": {"count": len(anomalies), "items": anomalies[:10]},
        "schema_changes": {"count": len(schema_changes), "items": schema_changes[:10]},
        "impact": impact_summary(session),
        "datasets": health_rows,
    }


@router.get("/settings")
def settings_view(settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    """Effective configuration that is safe to disclose (no connection strings or secrets)."""
    return {
        "version": __version__,
        "environment": settings.environment,
        "demo_mode": settings.demo_mode,
        "database_backend": settings.database_backend,
        "storage": {
            "usage_bytes": storage_for(settings).usage_bytes(),
            "location": str(settings.storage_dir) if settings.environment == "development" else "configured",
        },
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_rows": settings.max_rows,
            "max_columns": settings.max_columns,
            "max_cell_chars": settings.max_cell_chars,
            "max_versions_per_dataset": settings.max_versions_per_dataset,
            "preview_max_page_size": settings.preview_max_page_size,
            "regex_timeout_seconds": settings.regex_timeout_seconds,
        },
        "retention": {
            "user_data": "Kept until you delete the dataset or version. Deletion removes stored files immediately.",
            "lab_data_hours": settings.experiment_retention_hours,
            "lab_data": (
                "Generated fault-injection data expires automatically after "
                f"{settings.experiment_retention_hours} hours."
                if settings.experiment_retention_hours
                else "Generated fault-injection data is kept until the experiment is reset."
            ),
        },
        "privacy": {
            "external_services": [],
            "statement": "DataSentinel processes data locally. Uploaded datasets are never sent to external services "
            "or AI providers.",
        },
        "cors_origins": settings.cors_origins,
        "ml_detector_available": importlib.util.find_spec("sklearn") is not None,
        "detection_config": DEFAULT_CONFIG.as_dict(),
    }


@router.get("/samples")
def samples() -> dict[str, Any]:
    return {"datasets": SAMPLE_DATASETS, "planted_issues": PLANTED_ISSUES}


@router.post("/samples/load", status_code=201)
def load_samples(session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    """Import the bundled demo datasets, their quality rules and the demo lineage graph."""
    return load_demo_workspace(session, settings)


@router.post("/maintenance/integrity")
def run_integrity(session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    """Verify database consistency and every stored file against its recorded SHA-256 (read-only)."""
    return check_integrity(session, settings)


@router.post("/maintenance/retention")
def run_retention(session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    """Apply the retention policy now (delete expired fault-lab data)."""
    return {"expired_experiments_removed": purge_expired(session, settings)}
