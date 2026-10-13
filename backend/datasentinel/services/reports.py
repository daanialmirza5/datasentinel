"""Investigation reports (stored as JSON, exportable as JSON or Markdown)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from datasentinel import __version__
from datasentinel.config import Settings
from datasentinel.detection.anomalies import detect_within_version
from datasentinel.detection.signals import SEVERITY_RANK
from datasentinel.models import Dataset, DatasetVersion, Experiment, LineageAsset, Report, utcnow
from datasentinel.services import datasets as ds
from datasentinel.services.drift import get_or_compute_drift, version_ref
from datasentinel.services.impact import impact_analysis
from datasentinel.services.profiles import get_or_compute_profile
from datasentinel.services.validation import enabled_rules, latest_run, run_validation

DISCLAIMER = (
    "Signals are evidence for investigation, not proof of corruption. Downstream impact is derived from declared "
    "lineage only: 'suspected impact' and 'unverified risk' mean an asset depends on a failing input, not that its "
    "output is known to be wrong."
)


def _version_info(version: DatasetVersion) -> dict[str, Any]:
    return {
        **version_ref(version),
        "sha256": version.sha256,
        "original_filename": version.original_filename,
        "file_format": version.file_format,
        "column_count": version.column_count,
        "rejected_row_count": version.rejected_row_count,
        "origin": version.origin,
    }


def _quality_section(session: Session, settings: Settings, dataset: Dataset, version: DatasetVersion) -> dict:
    run = latest_run(session, dataset.id, version.id)
    if run is None and enabled_rules(session, dataset.id):
        run = run_validation(session, settings, dataset, version, trigger="report")
    if run is None:
        return {"status": "no_rules", "message": "No quality rules are defined for this dataset."}
    return {
        "status": "evaluated",
        "run_id": run.id,
        "evaluated_at": run.started_at.isoformat(),
        "summary": run.summary,
        "results": [
            {
                "rule_name": r.rule_name,
                "rule_type": r.rule_type,
                "column": r.column_name,
                "severity": r.severity,
                "status": r.status,
                "evaluated_count": r.evaluated_count,
                "violation_count": r.violation_count,
                "violation_pct": r.violation_pct,
                "message": r.message,
                "recommendation": r.recommendation,
                "examples": r.examples[:3],
            }
            for r in run.results
        ],
    }


def build_dataset_report(
    session: Session,
    settings: Settings,
    dataset: Dataset,
    version: DatasetVersion,
    base: DatasetVersion | None,
    title: str | None,
) -> dict[str, Any]:
    profile, _ = get_or_compute_profile(session, settings, version)
    p = profile.profile
    drift_section: dict[str, Any]
    if base is None:
        drift_section = {"status": "no_baseline", "message": "No earlier active version to compare against."}
    else:
        drift = get_or_compute_drift(session, settings, base, version).result
        drift_section = {
            "status": "compared",
            "base_version": version_ref(base),
            "summary": drift["summary"],
            "row_count": drift["row_count"],
            "schema_changes": drift["schema_changes"],
            "signals": [s for s in drift["signals"] if SEVERITY_RANK[s["severity"]] >= SEVERITY_RANK["low"]],
        }
    anomalies = detect_within_version(ds.load_table(settings, version), p)
    asset = session.scalar(select(LineageAsset).where(LineageAsset.dataset_id == dataset.id))
    impact = impact_analysis(session, asset) if asset else None
    return {
        "kind": "dataset",
        "title": title or f"Data quality investigation: {dataset.name} v{version.version_number}",
        "generated_at": utcnow().isoformat(),
        "generator": f"DataSentinel {__version__}",
        "dataset": {"id": dataset.id, "name": dataset.name, "description": dataset.description, "kind": dataset.kind},
        "version": _version_info(version),
        "profile_summary": {
            "row_count": p["row_count"],
            "column_count": p["column_count"],
            "duplicate_rows": p["duplicate_rows"],
            "missing_pct": p["missing_pct"],
            "columns": [
                {
                    "name": c["name"],
                    "type": c["type"],
                    "null_pct": c["null_pct"],
                    "distinct_count": c["distinct_count"],
                    "invalid_count": c["invalid_count"],
                }
                for c in p["columns"]
            ],
        },
        "quality": _quality_section(session, settings, dataset, version),
        "drift": drift_section,
        "anomalies": {
            "signals": anomalies["signals"],
            "time_series_column": anomalies["time_series"]["column"] if anomalies["time_series"] else None,
        },
        "impact": None
        if impact is None
        else {
            "origin_state": impact["origin_state"],
            "assessment": impact["assessment"],
            "counts": impact["counts"],
            "impacted": [
                {k: i[k] for k in ("name", "kind", "distance", "path", "classification", "evidence")}
                for i in impact["impacted"]
            ],
        },
        "recommendations": impact["recommendations"] if impact else [],
        "disclaimer": DISCLAIMER,
    }


def build_experiment_report(session: Session, experiment: Experiment, title: str | None) -> dict[str, Any]:
    dataset = session.get(Dataset, experiment.dataset_id)
    base = session.get(DatasetVersion, experiment.base_version_id)
    ev = experiment.evaluation
    return {
        "kind": "experiment",
        "title": title or f"Fault-injection experiment: {experiment.fault_type} on {dataset.name if dataset else '?'}",
        "generated_at": utcnow().isoformat(),
        "generator": f"DataSentinel {__version__}",
        "dataset": {"id": experiment.dataset_id, "name": dataset.name if dataset else None},
        "version": _version_info(base) if base else None,
        "experiment": {
            "id": experiment.id,
            "fault_type": experiment.fault_type,
            "params": experiment.params,
            "seed": experiment.seed,
            "modified_sha256": ev.get("modified_sha256"),
            "base_rows": ev.get("base_rows"),
            "modified_rows": ev.get("modified_rows"),
        },
        "ground_truth": {
            k: experiment.ground_truth.get(k)
            for k in ("scope", "affected_columns", "affected_rows", "expected", "examples")
        },
        "evaluation": {
            k: ev.get(k)
            for k in (
                "outcome",
                "detected",
                "counts",
                "matched_signals",
                "missed_signals",
                "true_positives",
                "false_positives",
                "signal_precision",
            )
        },
        "drift": {
            "status": "compared",
            "schema_changes": experiment.detection.get("schema_changes", []),
            "signals": [
                s
                for s in experiment.detection.get("signals", [])
                if SEVERITY_RANK[s["severity"]] >= SEVERITY_RANK["low"]
            ],
            "summary": experiment.detection.get("summary", {}),
        },
        "impact": {
            "origin_state": ev.get("simulated_impact", {}).get("simulated_origin_state"),
            "assessment": "Simulated: what would be affected if this modified data reached production.",
            "impacted": ev.get("simulated_impact", {}).get("impacted", []),
        },
        "recommendations": [],
        "disclaimer": DISCLAIMER,
    }


def create_report(
    session: Session,
    settings: Settings,
    *,
    dataset_id: str | None,
    version_id: str | None,
    base_version_id: str | None,
    experiment_id: str | None,
    title: str | None,
) -> Report:
    if experiment_id:
        from datasentinel.services.experiments import get_experiment

        experiment = get_experiment(session, experiment_id)
        content = build_experiment_report(session, experiment, title)
        report = Report(
            dataset_id=experiment.dataset_id,
            version_id=experiment.base_version_id,
            title=content["title"],
            content=content,
        )
    else:
        dataset = ds.get_dataset(session, dataset_id or "")
        version = ds.resolve_version(session, dataset, version_id)
        base = (
            ds.get_version(session, dataset, base_version_id)
            if base_version_id
            else ds.previous_version(session, version)
        )
        content = build_dataset_report(session, settings, dataset, version, base, title)
        report = Report(dataset_id=dataset.id, version_id=version.id, title=content["title"], content=content)
    session.add(report)
    session.flush()
    report.content = {**report.content, "report_id": report.id}
    session.flush()
    return report


# ---------------------------------------------------------------- Markdown


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "'")
    return re.sub(r"[\r\n]+", " ", text)[:300]


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return lines


def render_markdown(content: dict[str, Any]) -> str:
    md: list[str] = [f"# {_cell(content['title'])}", ""]
    md.append(f"_Generated {content['generated_at']} by {content['generator']}._")
    md.append("")
    dataset, version = content.get("dataset") or {}, content.get("version") or {}
    md.append(f"**Dataset:** {_cell(dataset.get('name'))}  ")
    if version:
        md.append(
            f"**Version:** {version.get('version_number')} ({_cell(version.get('original_filename'))}, "
            f"{version.get('row_count')} rows, imported {version.get('imported_at')})  "
        )
        md.append(f"**SHA-256:** `{version.get('sha256')}`")
    md.append("")

    if content["kind"] == "experiment":
        exp, gt, ev = content["experiment"], content["ground_truth"], content["evaluation"]
        md += [
            "## Experiment",
            "",
            f"- Fault: **{exp['fault_type']}** with parameters `{_cell(exp['params'])}`",
            f"- Seed: {exp['seed']} (modified data SHA-256 `{exp['modified_sha256']}`)",
            f"- Rows: {exp['base_rows']} → {exp['modified_rows']}",
            "",
            "## Ground truth",
            "",
            f"- Scope: {gt['scope']}; affected columns: "
            f"{', '.join(gt['affected_columns']) or 'dataset-level'}; affected rows: {gt['affected_rows']}",
            f"- Expected signals: {', '.join(gt['expected']['primary'])}",
            "",
            "## Evaluation",
            "",
            f"- Outcome: **{ev['outcome']}**",
            f"- True-positive signals: {ev['counts']['true_positive_signals']}; false positives: "
            f"{ev['counts']['false_positive_signals']}; missed expected signals: {ev['counts']['missed']}",
            "",
        ]
        if ev["false_positives"]:
            md += _table(
                ["False positive", "Column", "Severity"],
                [[f["title"], f["column"], f["severity"]] for f in ev["false_positives"]],
            ) + [""]
    else:
        prof = content["profile_summary"]
        md += [
            "## Profile",
            "",
            f"{prof['row_count']} rows × {prof['column_count']} columns; "
            f"{prof['duplicate_rows']} duplicate rows; {prof['missing_pct']:.2f}% of cells missing.",
            "",
        ]
        md += _table(
            ["Column", "Type", "Missing %", "Distinct", "Invalid"],
            [
                [c["name"], c["type"], f"{c['null_pct']:.2f}", c["distinct_count"], c["invalid_count"]]
                for c in prof["columns"]
            ],
        ) + [""]
        quality = content["quality"]
        md += ["## Quality rules", ""]
        if quality["status"] == "no_rules":
            md += [quality["message"], ""]
        else:
            s = quality["summary"]
            md += [
                f"{s['passed']} passed, {s['failed']} failed, {s['error']} errored, {s['not_evaluated']} not "
                f"evaluated (health: **{s['health']}**).",
                "",
            ]
            md += _table(
                ["Rule", "Column", "Severity", "Status", "Violations", "Detail"],
                [
                    [
                        r["rule_name"],
                        r["column"],
                        r["severity"],
                        r["status"],
                        f"{r['violation_count']} ({r['violation_pct']:.2f}%)",
                        r["message"],
                    ]
                    for r in quality["results"]
                ],
            ) + [""]
            failing = [r for r in quality["results"] if r["status"] == "failed" and r["examples"]]
            if failing:
                md += ["### Violation examples", ""]
                for r in failing:
                    rows = ", ".join(f"row {e['row']}: {_cell(e['values'])}" for e in r["examples"])
                    md.append(f"- **{_cell(r['rule_name'])}** — {rows}")
                md.append("")
        anomalies = content.get("anomalies", {}).get("signals", [])
        md += ["## Anomalies within this version", ""]
        md += (
            [f"- [{a['severity']}] {_cell(a['title'])} — {_cell(a['explanation'])}" for a in anomalies]
            or ["No within-version anomalies were found."]
        ) + [""]

    drift = content.get("drift", {})
    md += ["## Drift findings", ""]
    if drift.get("status") != "compared":
        md += [drift.get("message", "No comparison available."), ""]
    else:
        if drift.get("schema_changes"):
            md += ["### Schema changes", ""]
            md += _table(
                ["Change", "Column", "From", "To", "Severity"],
                [
                    [c["change_type"], c["column"], c.get("from"), c.get("to"), c["severity"]]
                    for c in drift["schema_changes"]
                ],
            ) + [""]
        md += ["### Signals", ""]
        md += (
            [f"- [{s['severity']}] **{_cell(s['title'])}** — {_cell(s['explanation'])}" for s in drift["signals"]]
            or ["No actionable signals."]
        ) + [""]

    impact = content.get("impact")
    md += ["## Downstream impact", ""]
    if not impact:
        md += ["This dataset is not connected to the lineage graph.", ""]
    else:
        md += [_cell(impact["assessment"]), ""]
        if impact["impacted"]:
            md += _table(
                ["Asset", "Kind", "Distance", "Classification", "Path"],
                [
                    [i["name"], i["kind"], i["distance"], i["classification"], " → ".join(i["path"])]
                    for i in impact["impacted"]
                ],
            ) + [""]
    if content.get("recommendations"):
        md += ["## Recommended actions", ""]
        for rec in content["recommendations"]:
            md.append(f"{rec['priority']}. **[{rec['kind']}] {_cell(rec['title'])}** — {_cell(rec['rationale'])}")
            for evidence in rec.get("evidence", [])[:3]:
                md.append(f"   - Evidence: {_cell(evidence)}")
        md.append("")
    md += ["---", "", f"_{content['disclaimer']}_", ""]
    return "\n".join(md)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "report"
