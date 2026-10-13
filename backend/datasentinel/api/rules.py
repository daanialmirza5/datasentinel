from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.api.deps import get_db, get_settings_dep
from datasentinel.config import Settings
from datasentinel.errors import NotFoundError, ValidationFailed
from datasentinel.models import Dataset, QualityRule, ValidationRun
from datasentinel.rules.engine import RULE_TYPES, SEVERITIES
from datasentinel.rules.params import PARAM_MODELS
from datasentinel.services import datasets as ds
from datasentinel.services.profiles import get_or_compute_profile
from datasentinel.services.validation import run_validation, suggest_rules

router = APIRouter(tags=["rules"])

RuleType = Literal[
    "column_exists",
    "not_null",
    "range",
    "expected_type",
    "pattern",
    "unique",
    "allowed_values",
    "aggregate_range",
    "timestamp_range",
    "row_count",
    "column_comparison",
    "foreign_key",
]
Severity = Literal["low", "medium", "high", "critical"]


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    rule_type: RuleType
    column_name: str | None = Field(default=None, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = "medium"
    enabled: bool = True
    description: str = Field(default="", max_length=2000)


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    column_name: str | None = Field(default=None, max_length=128)
    params: dict[str, Any] | None = None
    severity: Severity | None = None
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=2000)


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    name: str
    rule_type: str
    column_name: str | None
    params: dict[str, Any]
    severity: str
    enabled: bool
    description: str
    created_at: datetime
    updated_at: datetime


class RuleResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str | None
    rule_name: str
    rule_type: str
    column_name: str | None
    severity: str
    status: str
    evaluated_count: int
    violation_count: int
    violation_pct: float
    message: str
    recommendation: str
    examples: list[Any]
    details: dict[str, Any]


class ValidationRunOut(BaseModel):
    id: str
    dataset_id: str
    version_id: str
    version_number: int | None
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, Any]
    results: list[RuleResultOut] | None = None


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str | None = None
    rule_ids: list[str] | None = Field(
        default=None, max_length=500, description="Run only these rules (enabled or not). Default: all enabled."
    )


def _validated_params(session: Session, rule_type: str, column: str | None, params: dict[str, Any]) -> dict[str, Any]:
    if RULE_TYPES[rule_type]["requires_column"] and not column:
        raise ValidationFailed(f"Rule type '{rule_type}' requires column_name")
    try:
        model = PARAM_MODELS[rule_type].model_validate(params)
    except ValueError as exc:
        errors = getattr(exc, "errors", lambda: [])()
        raise ValidationFailed(
            "Invalid rule parameters",
            details=[{"location": [str(p) for p in e.get("loc", ())], "message": e.get("msg")} for e in errors]
            or str(exc),
        ) from exc
    if rule_type == "foreign_key" and session.get(Dataset, params["reference_dataset_id"]) is None:
        raise ValidationFailed("reference_dataset_id does not exist")
    return model.model_dump(mode="json")


def _rule_or_404(session: Session, rule_id: str) -> QualityRule:
    rule = session.get(QualityRule, rule_id)
    if rule is None:
        raise NotFoundError(f"Rule '{rule_id}' not found")
    return rule


def run_out(session: Session, run: ValidationRun, include_results: bool = True) -> ValidationRunOut:
    from datasentinel.models import DatasetVersion

    version = session.get(DatasetVersion, run.version_id)
    return ValidationRunOut(
        id=run.id,
        dataset_id=run.dataset_id,
        version_id=run.version_id,
        version_number=version.version_number if version else None,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary=run.summary,
        results=[RuleResultOut.model_validate(r) for r in run.results] if include_results else None,
    )


@router.get("/rule-types")
def rule_types() -> dict[str, Any]:
    """Catalogue of rule types with descriptions and JSON schemas for their parameters."""
    return {
        "severities": list(SEVERITIES),
        "types": [
            {
                "rule_type": key,
                "label": meta["label"],
                "description": meta["description"],
                "requires_column": meta["requires_column"],
                "scope": meta["scope"],
                "params_schema": PARAM_MODELS[key].model_json_schema(),
            }
            for key, meta in RULE_TYPES.items()
        ],
    }


@router.get("/datasets/{dataset_id}/rules", response_model=list[RuleOut])
def list_rules(dataset_id: str, session: Session = Depends(get_db)) -> list[RuleOut]:
    dataset = ds.get_dataset(session, dataset_id)
    return [RuleOut.model_validate(r) for r in dataset.rules]


@router.post("/datasets/{dataset_id}/rules", response_model=RuleOut, status_code=201)
def create_rule(dataset_id: str, body: RuleIn, session: Session = Depends(get_db)) -> RuleOut:
    dataset = ds.get_dataset(session, dataset_id)
    column = body.column_name if RULE_TYPES[body.rule_type]["requires_column"] else None
    params = _validated_params(session, body.rule_type, column, body.params)
    rule = QualityRule(
        dataset_id=dataset.id,
        name=body.name.strip(),
        rule_type=body.rule_type,
        column_name=column,
        params=params,
        severity=body.severity,
        enabled=body.enabled,
        description=body.description.strip(),
    )
    session.add(rule)
    session.flush()
    return RuleOut.model_validate(rule)


@router.get("/datasets/{dataset_id}/rules/suggestions")
def rule_suggestions(
    dataset_id: str, session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, Any]:
    """Rules suggested from the current version's profile. Nothing is created until you POST one."""
    dataset = ds.get_dataset(session, dataset_id)
    version = ds.resolve_version(session, dataset, None)
    profile, _ = get_or_compute_profile(session, settings, version)
    existing = {(r.rule_type, r.column_name) for r in dataset.rules}
    suggestions = [s for s in suggest_rules(profile.profile) if (s["rule_type"], s["column_name"]) not in existing]
    return {"version_id": version.id, "suggestions": suggestions}


@router.get("/rules/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: str, session: Session = Depends(get_db)) -> RuleOut:
    return RuleOut.model_validate(_rule_or_404(session, rule_id))


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, body: RuleUpdate, session: Session = Depends(get_db)) -> RuleOut:
    rule = _rule_or_404(session, rule_id)
    changes = body.model_dump(exclude_unset=True)
    column = changes.get("column_name", rule.column_name)
    if "params" in changes or "column_name" in changes:
        rule.params = _validated_params(session, rule.rule_type, column, changes.get("params", rule.params))
        rule.column_name = column if RULE_TYPES[rule.rule_type]["requires_column"] else None
    for key in ("name", "severity", "enabled", "description"):
        if changes.get(key) is not None:
            setattr(rule, key, changes[key].strip() if isinstance(changes[key], str) else changes[key])
    session.flush()
    return RuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    session.delete(_rule_or_404(session, rule_id))
    return {"deleted": True, "rule_id": rule_id}


@router.post("/datasets/{dataset_id}/validate", response_model=ValidationRunOut)
def validate(
    dataset_id: str,
    body: ValidateRequest | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> ValidationRunOut:
    """Run the dataset's enabled rules (or the listed rules) against a version and store the results."""
    body = body or ValidateRequest()
    dataset = ds.get_dataset(session, dataset_id)
    version = ds.resolve_version(session, dataset, body.version_id)
    if body.rule_ids:
        known = {r.id for r in dataset.rules}
        unknown = [r for r in body.rule_ids if r not in known]
        if unknown:
            raise ValidationFailed("Unknown rule ids for this dataset", details={"rule_ids": unknown})
    run = run_validation(session, settings, dataset, version, trigger="manual", rule_ids=body.rule_ids)
    return run_out(session, run)


@router.get("/datasets/{dataset_id}/validations", response_model=list[ValidationRunOut])
def list_validations(
    dataset_id: str,
    version_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Session = Depends(get_db),
) -> list[ValidationRunOut]:
    dataset = ds.get_dataset(session, dataset_id)
    query = select(ValidationRun).where(ValidationRun.dataset_id == dataset.id)
    if version_id:
        query = query.where(ValidationRun.version_id == version_id)
    runs = session.scalars(query.order_by(ValidationRun.started_at.desc()).limit(limit))
    return [run_out(session, run, include_results=False) for run in runs]


@router.get("/validations/{run_id}", response_model=ValidationRunOut)
def get_validation(run_id: str, session: Session = Depends(get_db)) -> ValidationRunOut:
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise NotFoundError(f"Validation run '{run_id}' not found")
    return run_out(session, run)
