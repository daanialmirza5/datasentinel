"""Rule-based, evidence-backed investigation and recovery recommendations.

Each recommendation names the evidence it is derived from (a failed rule, a schema change, a
statistical signal or a lineage path). Nothing here executes an action: quarantining a version or
restoring an earlier one is always a separate, explicit user action, and no data is deleted.
"""

from __future__ import annotations

from typing import Any

from datasentinel.detection.signals import SEVERITY_RANK
from datasentinel.rules.engine import RULE_TYPES

KIND_ORDER = {"contain": 0, "investigate": 1, "recover": 2, "verify": 3, "prevent": 4}

SIGNAL_ACTIONS: dict[str, tuple[str, str]] = {
    "column_removed": (
        "Inspect the recent source schema change for '{column}'",
        "The column disappeared from the latest version{rename}. Confirm with the producer whether it "
        "was dropped or renamed, then update consumers or restore the column.",
    ),
    "type_change": (
        "Inspect how the producer now formats '{column}'",
        "'{column}' changed type ({detail}). Restore the previous format at the source or add an explicit, "
        "tested cast before downstream use.",
    ),
    "null_rate_increase": (
        "Check extraction and joins feeding '{column}'",
        "Missing values in '{column}' rose significantly ({detail}). Typical causes are failed "
        "lookups/joins, optional source fields or a partial extract.",
    ),
    "nullability_change": (
        "Check why '{column}' is now sometimes empty",
        "The column was always populated before; consumers may assume it still is.",
    ),
    "numeric_outlier": (
        "Validate the expected range of '{column}'",
        "Extreme values increased ({detail}). Inspect the example rows for unit or scaling errors "
        "(cents vs. units, milliseconds vs. seconds) or sentinel values.",
    ),
    "distribution_shift": (
        "Confirm whether the shift in '{column}' is a real business change",
        "The distribution moved ({detail}). If it is not explained by a known business event, "
        "compare with the source system before trusting aggregates.",
    ),
    "new_category": (
        "Review the unexpected values in '{column}'",
        "New values appeared ({detail}). Either extend the allowed set (if legitimate) or fix the "
        "upstream mapping; joins and group-bys on this column may drop these rows.",
    ),
    "category_frequency_shift": (
        "Review the category mix of '{column}'",
        "The share of existing values changed ({detail}).",
    ),
    "uniqueness_lost": (
        "De-duplicate '{column}' before it is used as a key",
        "A previously unique column now repeats ({detail}); joins on it will fan out.",
    ),
    "duplicate_rows": (
        "Look for replayed or double-loaded batches",
        "Fully duplicated rows increased ({detail}); counts and sums downstream will be inflated.",
    ),
    "row_count_change": ("Check for partial or duplicated loads", "Row volume changed beyond tolerance ({detail})."),
    "timestamp_invalid": (
        "Check date formats and parsing for '{column}'",
        "Unparseable timestamps increased ({detail}).",
    ),
    "timestamp_out_of_range": (
        "Check time zones and default dates in '{column}'",
        "Future or pre-1971 timestamps appeared ({detail}).",
    ),
    "invalid_values": (
        "Inspect malformed values in '{column}'",
        "Values that do not match the column type increased ({detail}).",
    ),
}


def _signal_detail(signal: dict[str, Any]) -> str:
    ev = signal.get("evidence", {})
    if signal["category"] == "null_rate_increase":
        return f"{ev.get('base_pct', 0):.1f}% → {ev.get('candidate_pct', 0):.1f}%"
    if signal["category"] == "type_change":
        return f"{ev.get('from')} → {ev.get('to')}"
    if signal["category"] == "numeric_outlier":
        return f"{ev.get('candidate_count')} values beyond the baseline fences vs ≈{ev.get('expected')} expected"
    if signal["category"] == "distribution_shift":
        return f"KS D={ev.get('ks_statistic', 0):.2f}"
    if signal["category"] == "new_category":
        return ", ".join(f"'{k}'" for k in list(ev.get("new_values", {}))[:3])
    if signal["category"] == "row_count_change":
        return f"{ev.get('base')} → {ev.get('candidate')} rows"
    if signal["category"] == "duplicate_rows":
        return f"{ev.get('base')} → {ev.get('candidate')} duplicates"
    return signal.get("title", "")


def build_recommendations(
    origin_name: str,
    health: dict[str, Any],
    impacted: list[dict[str, Any]] | None = None,
    restore_candidate: dict[str, Any] | None = None,
    existing_rules: set[tuple[str | None, str]] | None = None,
) -> list[dict[str, Any]]:
    """Derive recommendations from an asset's health evidence and its downstream impact.

    ``existing_rules`` holds (column, rule_type) for every rule on the dataset, enabled or not, so a
    "add a rule" suggestion is never made for a rule that already exists.
    """
    recs: list[dict[str, Any]] = []
    impacted = impacted or []
    failed_rules = health.get("failed_rules", [])
    signals = [*health.get("breaking_changes", []), *health.get("anomaly_signals", [])]
    state = health.get("state")
    version_number = health.get("version_number")

    if state == "failing" and version_number is not None:
        worst = max(
            [SEVERITY_RANK.get(r["severity"], 0) for r in failed_rules]
            + [SEVERITY_RANK.get(s["severity"], 0) for s in signals]
            + [0]
        )
        if worst >= SEVERITY_RANK["high"]:
            recs.append(
                {
                    "kind": "contain",
                    "title": f"Quarantine version {version_number} of '{origin_name}'",
                    "rationale": "High-severity failures were confirmed on this version. Quarantining keeps the data "
                    "(nothing is deleted) and makes the previous active version current for consumers.",
                    "evidence": [f"rule '{r['rule_name']}' failed ({r['severity']})" for r in failed_rules[:3]]
                    + [s["title"] for s in signals if SEVERITY_RANK.get(s["severity"], 0) >= SEVERITY_RANK["high"]][:3],
                    "action": {
                        "type": "quarantine_version",
                        "dataset_id": health.get("dataset_id"),
                        "version_id": health.get("version_id"),
                    },
                }
            )

    for rule in failed_rules:
        recs.append(
            {
                "kind": "investigate",
                "title": f"Investigate failed rule '{rule['rule_name']}'",
                "rationale": rule.get("recommendation") or rule.get("message", ""),
                "evidence": [f"{rule['violation_count']} violation(s): {rule['message']}"],
            }
        )

    # A failed rule and a statistical signal often describe the same problem; keep the rule's item.
    seen: set[tuple[str, str | None]] = {
        (RULE_TYPES[r["rule_type"]]["signal_category"], r.get("column"))
        for r in failed_rules
        if r.get("rule_type") in RULE_TYPES
    }
    for signal in sorted(signals, key=lambda s: -SEVERITY_RANK.get(s["severity"], 0)):
        key = (signal["category"], signal.get("column"))
        if key in seen or signal["category"] not in SIGNAL_ACTIONS:
            continue
        seen.add(key)
        title, rationale = SIGNAL_ACTIONS[signal["category"]]
        rename_to = signal.get("evidence", {}).get("possible_rename_to")
        recs.append(
            {
                "kind": "investigate",
                "title": title.format(column=signal.get("column") or "dataset"),
                "rationale": rationale.format(
                    column=signal.get("column") or "dataset",
                    detail=_signal_detail(signal),
                    rename=f" (possibly renamed to '{rename_to}', unconfirmed)" if rename_to else "",
                ),
                "evidence": [signal["title"]],
            }
        )

    if state in ("failing", "anomalous"):
        if restore_candidate:
            recs.append(
                {
                    "kind": "recover",
                    "title": f"Restore the previously valid version {restore_candidate['version_number']}",
                    "rationale": f"Version {restore_candidate['version_number']} {restore_candidate['evidence']}. Quarantining "
                    f"version {version_number} makes it current again without deleting anything.",
                    "evidence": [restore_candidate["evidence"]],
                    "action": {
                        "type": "quarantine_version",
                        "dataset_id": health.get("dataset_id"),
                        "version_id": health.get("version_id"),
                    },
                }
            )
        else:
            recs.append(
                {
                    "kind": "recover",
                    "title": "Re-export the data from the source after the fix",
                    "rationale": "No earlier version with passing checks is available to fall back to.",
                    "evidence": ["no earlier version passed validation"],
                }
            )
        affected = [
            i for i in impacted if i["classification"] in ("confirmed_failure", "suspected_impact", "unverified_risk")
        ]
        if affected:
            names = ", ".join(i["name"] for i in affected[:6])
            recs.append(
                {
                    "kind": "verify",
                    "title": "Re-run downstream checks after correction",
                    "rationale": f"{len(affected)} downstream asset(s) depend on '{origin_name}': {names}. Their outputs "
                    "are not proven wrong, but they should be re-validated once the source is fixed.",
                    "evidence": [" → ".join(i["path"]) for i in affected[:3]],
                }
            )
            owners = sorted({i["owner"] for i in affected if i.get("owner")})
            consumers = [i["name"] for i in affected if i["kind"] in ("report", "model")]
            if consumers:
                recs.append(
                    {
                        "kind": "verify",
                        "title": "Notify owners of affected reports and models",
                        "rationale": f"Consumers at risk: {', '.join(consumers)}"
                        + (f" (owners: {', '.join(owners)})." if owners else "."),
                        "evidence": [f"{c} is downstream of '{origin_name}'" for c in consumers[:3]],
                    }
                )

    covered = set(existing_rules or set()) | {(r.get("column"), r.get("rule_type")) for r in failed_rules}
    rule_for = {"null_rate_increase": "not_null", "new_category": "allowed_values", "numeric_outlier": "range"}
    for signal in signals:
        column = signal.get("column")
        if column and signal["category"] in rule_for and (column, rule_for[signal["category"]]) not in covered:
            rule_type = rule_for[signal["category"]]
            recs.append(
                {
                    "kind": "prevent",
                    "title": f"Add a '{rule_type}' rule for '{column}'",
                    "rationale": "This problem was found statistically; an explicit rule turns the expectation into a "
                    "deterministic check that runs on every import.",
                    "evidence": [signal["title"]],
                }
            )
            covered.add((column, rule_type))

    recs.sort(key=lambda r: KIND_ORDER[r["kind"]])
    for index, rec in enumerate(recs, start=1):
        rec["priority"] = index
    return recs
