"""Running quality rules against dataset versions and persisting the results."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.models import Dataset, DatasetVersion, QualityRule, RuleResult, ValidationRun, utcnow
from datasentinel.rules.engine import EvalContext, RuleSpec, evaluate, recommendation_for
from datasentinel.services.datasets import LoadedTable, current_version, load_table

STATUS_ORDER = ("failed", "error", "not_evaluated", "passed")


def spec_for(rule: QualityRule) -> RuleSpec:
    return RuleSpec(rule.rule_type, rule.column_name, dict(rule.params or {}), rule.name, rule.severity)


def reference_resolver(session: Session, settings: Settings) -> Callable[[str], LoadedTable | None]:
    def resolve(dataset_id: str) -> LoadedTable | None:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            return None
        version = current_version(session, dataset)
        return load_table(settings, version) if version is not None else None

    return resolve


def evaluate_rules(
    table: LoadedTable, rules: Iterable[QualityRule], settings: Settings, resolver: Callable[[str], LoadedTable | None]
) -> list[dict[str, Any]]:
    """Evaluate rules in memory and return plain result dicts (used by validation runs and the lab)."""
    ctx = EvalContext(
        table=table,
        resolve_reference=resolver,
        example_limit=settings.rule_example_limit,
        regex_timeout_seconds=settings.regex_timeout_seconds,
    )
    results = []
    for rule in rules:
        spec = spec_for(rule)
        outcome = evaluate(spec, ctx)
        results.append(
            {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "rule_type": rule.rule_type,
                "column_name": rule.column_name,
                "severity": rule.severity,
                "status": outcome.status,
                "evaluated_count": outcome.evaluated_count,
                "violation_count": outcome.violation_count,
                "violation_pct": outcome.violation_pct,
                "message": outcome.message,
                "examples": outcome.examples,
                "details": outcome.details,
                "params": dict(rule.params or {}),
                "recommendation": recommendation_for(spec) if outcome.status in ("failed", "error") else "",
            }
        )
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {status: 0 for status in STATUS_ORDER}
    failed_by_severity = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        if result["status"] == "failed":
            failed_by_severity[result["severity"]] = failed_by_severity.get(result["severity"], 0) + 1
    if not results:
        health = "no_rules"
    elif counts["failed"] or counts["error"]:
        health = "failing"
    elif counts["not_evaluated"]:
        health = "incomplete"
    else:
        health = "passing"
    return {"total": len(results), **counts, "failed_by_severity": failed_by_severity, "health": health}


def enabled_rules(session: Session, dataset_id: str, rule_ids: list[str] | None = None) -> list[QualityRule]:
    query = select(QualityRule).where(QualityRule.dataset_id == dataset_id).order_by(QualityRule.created_at)
    if rule_ids:
        query = query.where(QualityRule.id.in_(rule_ids))
    else:
        query = query.where(QualityRule.enabled.is_(True))
    return list(session.scalars(query))


def run_validation(
    session: Session,
    settings: Settings,
    dataset: Dataset,
    version: DatasetVersion,
    *,
    trigger: str = "manual",
    rule_ids: list[str] | None = None,
) -> ValidationRun:
    rules = enabled_rules(session, dataset.id, rule_ids)
    run = ValidationRun(dataset_id=dataset.id, version_id=version.id, trigger=trigger)
    session.add(run)
    session.flush()
    results = evaluate_rules(load_table(settings, version), rules, settings, reference_resolver(session, settings))
    for result in results:
        session.add(RuleResult(run_id=run.id, **{k: v for k, v in result.items() if k != "params"}))
    run.summary = summarize(results)
    run.finished_at = utcnow()
    session.flush()
    session.refresh(run)
    return run


def latest_run(session: Session, dataset_id: str, version_id: str | None = None) -> ValidationRun | None:
    query = select(ValidationRun).where(ValidationRun.dataset_id == dataset_id)
    if version_id:
        query = query.where(ValidationRun.version_id == version_id)
    return session.scalars(query.order_by(ValidationRun.started_at.desc()).limit(1)).first()


def suggest_rules(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Conservative rule suggestions derived from an observed profile (never created automatically)."""
    suggestions: list[dict[str, Any]] = []
    rows = profile.get("row_count", 0)
    for column in profile.get("columns", []):
        name, kind = column["name"], column["type"]
        if kind == "empty":
            continue
        suggestions.append(
            {
                "name": f"{name} exists",
                "rule_type": "column_exists",
                "column_name": name,
                "params": {},
                "severity": "high",
                "reason": "Downstream consumers usually depend on every column being present.",
            }
        )
        if column["null_count"] == 0 and rows >= 10:
            suggestions.append(
                {
                    "name": f"{name} not null",
                    "rule_type": "not_null",
                    "column_name": name,
                    "params": {"max_null_pct": 0},
                    "severity": "medium",
                    "reason": "No missing values were observed.",
                }
            )
        if column.get("unique") and kind in ("integer", "string") and rows >= 10:
            suggestions.append(
                {
                    "name": f"{name} unique",
                    "rule_type": "unique",
                    "column_name": name,
                    "params": {},
                    "severity": "high",
                    "reason": "Every observed value is distinct; this looks like a key.",
                }
            )
        if kind in ("integer", "float"):
            suggestions.append(
                {
                    "name": f"{name} type",
                    "rule_type": "expected_type",
                    "column_name": name,
                    "params": {"type": "float" if kind == "float" else "integer"},
                    "severity": "high",
                    "reason": f"Column is consistently {kind}.",
                }
            )
            if column.get("min") is not None and column.get("min", 0) >= 0:
                suggestions.append(
                    {
                        "name": f"{name} non-negative",
                        "rule_type": "range",
                        "column_name": name,
                        "params": {"min": 0},
                        "severity": "medium",
                        "reason": "No negative values were observed.",
                    }
                )
        if column.get("is_categorical") and kind == "string" and column["distinct_count"] <= 20:
            suggestions.append(
                {
                    "name": f"{name} allowed values",
                    "rule_type": "allowed_values",
                    "column_name": name,
                    "params": {"values": [c["value"] for c in column.get("categories", [])]},
                    "severity": "medium",
                    "reason": f"Only {column['distinct_count']} distinct values were observed.",
                }
            )
        if kind == "datetime":
            suggestions.append(
                {
                    "name": f"{name} not in future",
                    "rule_type": "timestamp_range",
                    "column_name": name,
                    "params": {"max_future_days": 1},
                    "severity": "medium",
                    "reason": "Event timestamps should not be in the future.",
                }
            )
    if rows:
        suggestions.append(
            {
                "name": "row count floor",
                "rule_type": "row_count",
                "column_name": None,
                "params": {"min": max(1, int(rows * 0.5))},
                "severity": "medium",
                "reason": f"Observed {rows} rows; alert if a version has less than half.",
            }
        )
    return suggestions
