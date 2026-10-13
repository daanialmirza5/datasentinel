from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datasentinel.api.deps import get_db, get_settings_dep
from datasentinel.config import Settings
from datasentinel.errors import NotFoundError
from datasentinel.models import Report
from datasentinel.services import reports as svc

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None = Field(default=None, max_length=40)
    version_id: str | None = Field(default=None, max_length=40)
    base_version_id: str | None = Field(default=None, max_length=40)
    experiment_id: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _target(self) -> ReportIn:
        if bool(self.dataset_id) == bool(self.experiment_id):
            raise ValueError("Provide exactly one of dataset_id or experiment_id")
        return self


def _report(session: Session, report_id: str) -> Report:
    report = session.get(Report, report_id)
    if report is None:
        raise NotFoundError(f"Report '{report_id}' not found")
    return report


def _summary(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "title": report.title,
        "kind": report.content.get("kind"),
        "dataset_id": report.dataset_id,
        "version_id": report.version_id,
        "created_at": report.created_at.isoformat(),
    }


@router.post("", status_code=201)
def create_report(
    body: ReportIn, session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, Any]:
    """Generate an investigation report for a dataset version (quality, drift, anomalies, impact,
    recommendations) or for a fault-injection experiment."""
    report = svc.create_report(
        session,
        settings,
        dataset_id=body.dataset_id,
        version_id=body.version_id,
        base_version_id=body.base_version_id,
        experiment_id=body.experiment_id,
        title=body.title,
    )
    return {**_summary(report), "content": report.content}


@router.get("")
def list_reports(
    dataset_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(Report)
    if dataset_id:
        query = query.where(Report.dataset_id == dataset_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(Report.created_at.desc()).limit(limit).offset(offset))
    return {"items": [_summary(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{report_id}")
def get_report(report_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    report = _report(session, report_id)
    return {**_summary(report), "content": report.content}


@router.get("/{report_id}/export")
def export_report(
    report_id: str, format: Literal["json", "markdown"] = "markdown", session: Session = Depends(get_db)
) -> Response:
    """Download the report as Markdown or JSON."""
    report = _report(session, report_id)
    name = f"datasentinel-{svc.slug(report.title)}-{report.id[-6:]}"
    if format == "json":
        return Response(
            json.dumps(report.content, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )
    return Response(
        svc.render_markdown(report.content),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )


@router.delete("/{report_id}")
def delete_report(report_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    session.delete(_report(session, report_id))
    return {"deleted": True, "report_id": report_id}
