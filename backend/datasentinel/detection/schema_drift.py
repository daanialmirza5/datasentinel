"""Schema drift between two versions of a dataset.

Detects added/removed columns, type changes and nullability changes, and proposes *possible*
renames. Rename inference is deliberately conservative: a removed and an added column are paired
only when their types are compatible and their values look alike (distribution similarity) and,
for the stronger "likely" label, their names are also similar. The output never claims a rename
is confirmed — only the producer of the data can confirm that.
"""

from __future__ import annotations

import difflib
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from datasentinel.detection.signals import Signal
from datasentinel.services.datasets import LoadedTable

NUMERIC = {"integer", "float"}
LIKELY_RENAME_SCORE = 0.8
POSSIBLE_RENAME_SCORE = 0.6

TYPE_CHANGE_SEVERITY = {
    ("integer", "float"): "low",
    ("float", "integer"): "low",
}


def _type_change_severity(old: str, new: str) -> str:
    if (old, new) in TYPE_CHANGE_SEVERITY:
        return TYPE_CHANGE_SEVERITY[(old, new)]
    if new == "empty":
        return "high"
    if old in NUMERIC | {"datetime", "boolean"} and new == "string":
        return "critical"
    return "medium"


def _name_similarity(a: str, b: str) -> float:
    a_l, b_l = a.lower(), b.lower()
    if a_l in b_l or b_l in a_l:
        return 0.9
    return difflib.SequenceMatcher(None, a_l, b_l).ratio()


def _value_similarity(base: LoadedTable, old: str, cand: LoadedTable, new: str, kind: str) -> float:
    if kind in NUMERIC or kind == "datetime":
        left = base.typed[old].dropna()
        right = cand.typed[new].dropna()
        if kind == "datetime":
            left, right = left.astype("int64"), right.astype("int64")
        if len(left) < 5 or len(right) < 5:
            return 0.0
        statistic = stats.ks_2samp(left.to_numpy(dtype=float), right.to_numpy(dtype=float)).statistic
        return float(1.0 - statistic)
    left_values = set(base.raw[old].dropna().astype(str).value_counts().head(200).index)
    right_values = set(cand.raw[new].dropna().astype(str).value_counts().head(200).index)
    if not left_values or not right_values:
        return 0.0
    return len(left_values & right_values) / len(left_values | right_values)


def _null_similarity(base: LoadedTable, old: str, cand: LoadedTable, new: str) -> float:
    left = float(base.raw[old].isna().mean()) if len(base.raw) else 0.0
    right = float(cand.raw[new].isna().mean()) if len(cand.raw) else 0.0
    return max(0.0, 1.0 - abs(left - right) / 0.10)


def rename_candidates(base: LoadedTable, cand: LoadedTable, removed: list[str], added: list[str]) -> list[dict]:
    """Greedy one-to-one pairing of removed→added columns by evidence score."""
    base_types = {i.name: i.inferred_type for i in base.inferences}
    cand_types = {i.name: i.inferred_type for i in cand.inferences}
    scored = []
    for old in removed:
        for new in added:
            t_old, t_new = base_types[old], cand_types[new]
            compatible = t_old == t_new or {t_old, t_new} <= NUMERIC
            if not compatible or t_old == "empty":
                continue
            kind = "float" if {t_old, t_new} <= NUMERIC else t_old
            value_sim = _value_similarity(base, old, cand, new, kind)
            null_sim = _null_similarity(base, old, cand, new)
            name_sim = _name_similarity(old, new)
            score = 0.5 * value_sim + 0.2 * null_sim + 0.3 * name_sim
            scored.append(
                (
                    score,
                    old,
                    new,
                    {
                        "value_similarity": round(value_sim, 4),
                        "null_rate_similarity": round(null_sim, 4),
                        "name_similarity": round(name_sim, 4),
                        "score": round(score, 4),
                    },
                )
            )
    pairs, used_old, used_new = [], set(), set()
    for score, old, new, evidence in sorted(scored, key=lambda item: -item[0]):
        if old in used_old or new in used_new or score < POSSIBLE_RENAME_SCORE:
            continue
        likely = score >= LIKELY_RENAME_SCORE and evidence["name_similarity"] >= 0.5
        pairs.append({"from": old, "to": new, "confidence": "likely" if likely else "possible", "evidence": evidence})
        used_old.add(old)
        used_new.add(new)
    return pairs


def compare_schemas(base: LoadedTable, cand: LoadedTable) -> tuple[list[dict[str, Any]], list[Signal]]:
    base_cols = [i.name for i in base.inferences]
    cand_cols = [i.name for i in cand.inferences]
    base_inf = {i.name: i for i in base.inferences}
    cand_inf = {i.name: i for i in cand.inferences}
    removed = [c for c in base_cols if c not in cand_inf]
    added = [c for c in cand_cols if c not in base_inf]
    renames = rename_candidates(base, cand, removed, added)
    rename_from = {r["from"]: r for r in renames}
    rename_to = {r["to"]: r for r in renames}

    changes: list[dict[str, Any]] = []
    signals: list[Signal] = []

    for column in removed:
        rename = rename_from.get(column)
        hint = (
            f" It may have been renamed to '{rename['to']}' ({rename['confidence']} rename, evidence score "
            f"{rename['evidence']['score']}); this is not confirmed."
            if rename
            else ""
        )
        explanation = (
            f"Column '{column}' ({base_inf[column].inferred_type}) is absent from the new version. "
            f"Consumers that select it by name will fail or silently receive missing values.{hint}"
        )
        changes.append(
            {
                "change_type": "removed",
                "column": column,
                "from": base_inf[column].inferred_type,
                "to": None,
                "severity": "high",
                "explanation": explanation,
                "possible_rename_to": rename["to"] if rename else None,
            }
        )
        signals.append(
            Signal(
                "column_removed",
                "high",
                f"Column '{column}' removed",
                explanation,
                column,
                "schema",
                {
                    "previous_type": base_inf[column].inferred_type,
                    "possible_rename_to": rename["to"] if rename else None,
                },
            )
        )

    for column in added:
        rename = rename_to.get(column)
        explanation = (
            f"Column '{column}' ({cand_inf[column].inferred_type}) is new. New columns are usually "
            "harmless but signal a producer change" + (f"; it may replace '{rename['from']}'." if rename else ".")
        )
        changes.append(
            {
                "change_type": "added",
                "column": column,
                "from": None,
                "to": cand_inf[column].inferred_type,
                "severity": "low",
                "explanation": explanation,
                "possible_rename_of": rename["from"] if rename else None,
            }
        )
        signals.append(
            Signal(
                "column_added",
                "low",
                f"Column '{column}' added",
                explanation,
                column,
                "schema",
                {"type": cand_inf[column].inferred_type},
            )
        )

    for rename in renames:
        explanation = (
            f"'{rename['from']}' was removed and '{rename['to']}' added with similar values "
            f"(evidence score {rename['evidence']['score']}). This is a {rename['confidence']} rename, "
            "not a confirmed one; confirm with the data producer."
        )
        changes.append(
            {
                "change_type": f"{rename['confidence']}_rename",
                "column": rename["to"],
                "from": rename["from"],
                "to": rename["to"],
                "severity": "medium",
                "explanation": explanation,
                "evidence": rename["evidence"],
            }
        )
        signals.append(
            Signal(
                "possible_rename",
                "info",
                f"'{rename['from']}' → '{rename['to']}' ({rename['confidence']} rename)",
                explanation,
                rename["to"],
                "schema",
                {**rename["evidence"], "from": rename["from"], "confidence": rename["confidence"]},
            )
        )

    for column in base_cols:
        if column not in cand_inf:
            continue
        old, new = base_inf[column], cand_inf[column]
        if old.inferred_type != new.inferred_type:
            severity = _type_change_severity(old.inferred_type, new.inferred_type)
            examples = new.invalid_examples or [str(v) for v in pd.unique(cand.raw[column].dropna())[:5]]
            explanation = f"Column '{column}' changed from {old.inferred_type} to {new.inferred_type}. " + (
                "Numeric or temporal operations on this column will fail or silently coerce values."
                if severity == "critical"
                else "Check that downstream casts still behave as expected."
            )
            changes.append(
                {
                    "change_type": "type_change",
                    "column": column,
                    "from": old.inferred_type,
                    "to": new.inferred_type,
                    "severity": severity,
                    "explanation": explanation,
                    "examples": examples[:5],
                }
            )
            signals.append(
                Signal(
                    "type_change",
                    severity,
                    f"'{column}' type {old.inferred_type} → {new.inferred_type}",
                    explanation,
                    column,
                    "schema",
                    {
                        "from": old.inferred_type,
                        "to": new.inferred_type,
                        "examples": examples[:5],
                        "numeric_like_pct": new.numeric_like_pct,
                    },
                )
            )
        base_nulls = int(base.raw[column].isna().sum())
        cand_nulls = int(cand.raw[column].isna().sum())
        if base_nulls == 0 and cand_nulls > 0 and len(base.raw) >= 10:
            pct = 100.0 * cand_nulls / max(len(cand.raw), 1)
            explanation = (
                f"Column '{column}' had no missing values in the previous version and now has {cand_nulls} "
                f"({pct:.2f}%). Consumers that assume it is always populated may break."
            )
            changes.append(
                {
                    "change_type": "nullability_change",
                    "column": column,
                    "from": "never null",
                    "to": "nullable",
                    "severity": "medium",
                    "explanation": explanation,
                }
            )
            signals.append(
                Signal(
                    "nullability_change",
                    "medium",
                    f"'{column}' now contains missing values",
                    explanation,
                    column,
                    "schema",
                    {"previous_nulls": 0, "current_nulls": cand_nulls, "current_null_pct": round(pct, 4)},
                )
            )
    order = list(np.argsort([c["column"] or "" for c in changes], kind="stable"))
    return [changes[i] for i in order], signals
