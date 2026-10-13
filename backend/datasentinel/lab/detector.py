"""Detection as run by the lab and the benchmark.

Combines the version-to-version detection pipeline with the dataset's enabled quality rules. A rule
contributes a signal only if it fails on the candidate but did *not* fail on the baseline, so
pre-existing failures are not attributed to the new data. This function receives the two tables,
their profiles and the rules — never the experiment or its ground truth.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from datasentinel.config import Settings
from datasentinel.detection.pipeline import detect_changes, summarize_signals
from datasentinel.detection.signals import Signal, sort_signals
from datasentinel.models import QualityRule
from datasentinel.rules.engine import RULE_TYPES
from datasentinel.services.datasets import LoadedTable
from datasentinel.services.validation import evaluate_rules


def _rule_columns(result: dict[str, Any], params: dict[str, Any]) -> list[str]:
    columns = [result["column_name"]] if result["column_name"] else []
    if params.get("other_column"):
        columns.append(params["other_column"])
    columns.extend(params.get("extra_columns", []))
    return columns


def rule_signals(base_results: list[dict[str, Any]], cand_results: list[dict[str, Any]]) -> list[Signal]:
    before = {r["rule_id"]: r["status"] for r in base_results}
    params_by_rule = {r["rule_id"]: r.get("params", {}) for r in cand_results}
    signals = []
    for result in cand_results:
        if result["status"] != "failed" or before.get(result["rule_id"]) == "failed":
            continue
        category = RULE_TYPES[result["rule_type"]]["signal_category"]
        column = (
            result["column_name"]
            if RULE_TYPES[result["rule_type"]]["scope"] != "dataset" or result["rule_type"] == "aggregate_range"
            else None
        )
        signals.append(
            Signal(
                category,
                result["severity"],
                f"Rule '{result['rule_name']}' now fails",
                f"{result['message']} The rule passed (or was not evaluated) on the baseline version.",
                column,
                "rule",
                {
                    "rule_id": result["rule_id"],
                    "rule_type": result["rule_type"],
                    # Every column the rule inspects, so evaluation can attribute multi-column rules.
                    "columns": _rule_columns(result, params_by_rule.get(result["rule_id"], {})),
                    "violation_count": result["violation_count"],
                    "violation_pct": result["violation_pct"],
                    "examples": result["examples"][:3],
                },
            )
        )
    return signals


def run_detection(
    base: LoadedTable,
    cand: LoadedTable,
    base_profile: dict[str, Any],
    cand_profile: dict[str, Any],
    rules: Iterable[QualityRule],
    settings: Settings,
    resolver: Callable[[str], LoadedTable | None],
) -> dict[str, Any]:
    rules = list(rules)
    drift = detect_changes(base, cand, base_profile, cand_profile)
    base_results = evaluate_rules(base, rules, settings, resolver)
    cand_results = evaluate_rules(cand, rules, settings, resolver)
    from_rules = [s.as_dict() for s in rule_signals(base_results, cand_results)]
    signals = sort_signals([*drift["signals"], *from_rules])
    return {
        "signals": signals,
        "summary": summarize_signals(signals, len(drift["schema_changes"])),
        "schema_changes": drift["schema_changes"],
        "column_comparisons": drift["column_comparisons"],
        "row_count": drift["row_count"],
        "duplicates": drift["duplicates"],
        "rule_results": {"baseline": base_results, "candidate": cand_results},
        "rules_evaluated": len(rules),
    }
