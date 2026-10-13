"""The common currency of detection: a *signal* is evidence that something deserves investigation.

A signal is not proof of corruption. Each one carries a category (what kind of change), an
optional column, a severity, a human explanation and machine-readable evidence (test statistics,
counts, examples) so every claim in the UI and in reports can be traced back to data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

CATEGORY_LABELS = {
    "column_added": "Column added",
    "column_removed": "Column removed",
    "possible_rename": "Possible column rename",
    "type_change": "Type change",
    "nullability_change": "Nullability change",
    "null_rate_increase": "Missing values increased",
    "null_rate_decrease": "Missing values decreased",
    "invalid_values": "Invalid values increased",
    "timestamp_invalid": "Unparseable timestamps increased",
    "timestamp_out_of_range": "Implausible timestamps",
    "distribution_shift": "Distribution shift",
    "numeric_outlier": "Numeric outliers increased",
    "new_category": "Unexpected categories",
    "category_missing": "Categories disappeared",
    "category_frequency_shift": "Category mix changed",
    "uniqueness_lost": "Uniqueness lost",
    "row_count_change": "Row count changed",
    "duplicate_rows": "Duplicate rows increased",
    "time_series_deviation": "Time-series deviation",
    "rule_failure": "Quality rule failed",
}


@dataclass
class Signal:
    category: str
    severity: str
    title: str
    explanation: str
    column: str | None = None
    source: str = "statistics"  # schema | statistics | rule | time_series | ml
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.category}:{self.column or '*'}"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        data["label"] = CATEGORY_LABELS.get(self.category, self.category)
        return data


def severity_max(signals: list[dict[str, Any]]) -> str | None:
    if not signals:
        return None
    return max((s["severity"] for s in signals), key=lambda s: SEVERITY_RANK.get(s, 0))


def severity_counts(signals: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(SEVERITY_RANK, 0)
    for signal in signals:
        counts[signal["severity"]] = counts.get(signal["severity"], 0) + 1
    return counts


def sort_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(signals, key=lambda s: (-SEVERITY_RANK.get(s["severity"], 0), s["category"], s.get("column") or ""))
