"""Scoring detector output against an experiment's ground truth.

Only *actionable* signals (severity low or higher) are scored; ``info`` signals such as
"missing values decreased" or rename hints are context, not alarms.

A detector signal is **relevant** to the injected fault when its category is one of the fault's
expected (primary) or accepted (consequential) categories *and* it points at an affected column —
or, for dataset-scoped faults (duplicates, row removal), when it is dataset-level or a
``uniqueness_lost`` signal. Relevant signals are true positives; every other actionable signal is a
false positive. An expected (primary) signal is *missed* when no true positive of that category was
raised for the affected column(s). The scenario counts as *detected* when at least one true
positive of a primary category exists.
"""

from __future__ import annotations

from typing import Any

from datasentinel.detection.signals import SEVERITY_RANK

DATASET_SCOPE_COLUMN_CATEGORIES = {"uniqueness_lost"}


def actionable(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in signals if SEVERITY_RANK.get(s["severity"], 0) >= SEVERITY_RANK["low"]]


def is_relevant(signal: dict[str, Any], truth: dict[str, Any]) -> bool:
    expected = truth["expected"]
    if signal["category"] not in set(expected["primary"]) | set(expected["accepted"]):
        return False
    if truth["scope"] == "dataset":
        return signal.get("column") is None or signal["category"] in DATASET_SCOPE_COLUMN_CATEGORIES
    return signal.get("column") in set(truth["affected_columns"])


def evaluate(truth: dict[str, Any], signals: list[dict[str, Any]]) -> dict[str, Any]:
    scored = actionable(signals)
    true_pos = [s for s in scored if is_relevant(s, truth)]
    false_pos = [s for s in scored if not is_relevant(s, truth)]
    targets = truth["affected_columns"] if truth["scope"] == "column" else [None]
    expected = [{"category": c, "column": col} for c in truth["expected"]["primary"] for col in targets]
    found = {(s["category"], s.get("column") if truth["scope"] == "column" else None) for s in true_pos}
    matched = [e for e in expected if (e["category"], e["column"]) in found]
    missed = [e for e in expected if (e["category"], e["column"]) not in found]
    detected = bool(matched)

    def brief(s: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": s["key"],
            "category": s["category"],
            "column": s.get("column"),
            "severity": s["severity"],
            "title": s["title"],
            "source": s.get("source"),
        }

    return {
        "detected": detected,
        "outcome": "detected" if detected else ("missed" if not true_pos else "partially_detected"),
        "expected_signals": expected,
        "matched_signals": matched,
        "missed_signals": missed,
        "true_positives": [brief(s) for s in true_pos],
        "false_positives": [brief(s) for s in false_pos],
        "counts": {
            "expected": len(expected),
            "matched": len(matched),
            "missed": len(missed),
            "true_positive_signals": len(true_pos),
            "false_positive_signals": len(false_pos),
            "actionable_signals": len(scored),
        },
        "signal_precision": round(len(true_pos) / len(scored), 4) if scored else None,
        "expected_recall": round(len(matched) / len(expected), 4) if expected else None,
    }


def evaluate_healthy(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """For control scenarios with no injected fault: every actionable signal is a false positive."""
    scored = actionable(signals)
    return {
        "alarm": bool(scored),
        "false_positive_signals": len(scored),
        "false_positives": [
            {
                "key": s["key"],
                "category": s["category"],
                "column": s.get("column"),
                "severity": s["severity"],
                "title": s["title"],
            }
            for s in scored
        ],
    }
