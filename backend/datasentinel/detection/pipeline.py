"""The detection pipeline shared by drift monitoring, the fault-injection lab and the benchmark.

``detect_changes`` sees only the two tables (and their profiles). It has no access to experiment
metadata, so it cannot be told which fault was injected.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from datasentinel.detection.schema_drift import compare_schemas
from datasentinel.detection.signals import SEVERITY_RANK, Signal, severity_counts, severity_max, sort_signals
from datasentinel.detection.statistics import DetectionConfig, compare_columns, compare_dataset
from datasentinel.services.datasets import LoadedTable

DRIFT_ALGORITHM_VERSION = "1.4"
DEFAULT_CONFIG = DetectionConfig()


def summarize_signals(signals: list[dict[str, Any]], schema_changes: int = 0) -> dict[str, Any]:
    actionable = [s for s in signals if SEVERITY_RANK.get(s["severity"], 0) >= SEVERITY_RANK["low"]]
    return {
        "schema_change_count": schema_changes,
        "signal_count": len(signals),
        "actionable_signal_count": len(actionable),
        "max_severity": severity_max(actionable),
        "by_severity": severity_counts(signals),
        "by_category": dict(Counter(s["category"] for s in signals)),
    }


def detect_changes(
    base: LoadedTable,
    cand: LoadedTable,
    base_profile: dict[str, Any],
    cand_profile: dict[str, Any],
    cfg: DetectionConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    signals: list[Signal] = []
    schema_changes, schema_signals = compare_schemas(base, cand)
    signals.extend(schema_signals)
    dataset_level = compare_dataset(base, cand, base_profile, cand_profile, cfg, signals)
    comparisons = compare_columns(base, cand, base_profile, cand_profile, cfg, signals)
    signal_dicts = sort_signals([s.as_dict() for s in signals])
    return {
        "algorithm_version": DRIFT_ALGORITHM_VERSION,
        "config": cfg.as_dict(),
        "row_count": dataset_level["row_count"],
        "duplicates": dataset_level["duplicates"],
        "schema_changes": schema_changes,
        "column_comparisons": comparisons,
        "signals": signal_dicts,
        "summary": summarize_signals(signal_dicts, len(schema_changes)),
    }
