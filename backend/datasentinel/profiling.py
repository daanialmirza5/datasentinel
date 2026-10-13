"""Column and dataset profiling.

All statistics are *exact* — computed over every row of the version, not a sample. Histograms are
binned summaries of the exact data (their bin edges are reported). Profiles are cached per version
in the database together with ``ALGORITHM_VERSION`` so they are recomputed only if the algorithm
changes.

Conventions:

* ``null_pct``, ``distinct_pct`` etc. are percentages in [0, 100].
* ``std`` is the sample standard deviation (ddof=1); it is ``None`` for fewer than two values.
* Outlier counts use Tukey fences (1.5 × IQR) and the modified z-score (|0.6745·(x − median)/MAD|
  > 3.5, Iglewicz & Hoaglin 1993). Both are reported as ``None`` when not meaningful (n < 8, or
  zero spread).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from datasentinel.services.datasets import LoadedTable, count_duplicate_rows

ALGORITHM_VERSION = "1.0"
CATEGORICAL_MAX_DISTINCT = 50
CATEGORICAL_MAX_RATIO = 0.2
HISTOGRAM_BINS = 20
MIN_ROWS_FOR_OUTLIERS = 8
MAD_THRESHOLD = 3.5
QUANTILES = {"p01": 0.01, "p05": 0.05, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p95": 0.95, "p99": 0.99}


def clean(value: Any) -> Any:
    """Convert numpy/pandas scalars to JSON-safe Python values (NaN/inf -> None)."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _pct(part: int | float, whole: int | float) -> float:
    return round(100.0 * part / whole, 4) if whole else 0.0


def mad_outlier_mask(values: np.ndarray) -> np.ndarray | None:
    if values.size < MIN_ROWS_FOR_OUTLIERS:
        return None
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        return None
    return np.abs(0.6745 * (values - median) / mad) > MAD_THRESHOLD


def iqr_fences(values: np.ndarray, k: float = 1.5) -> tuple[float, float] | None:
    if values.size < MIN_ROWS_FOR_OUTLIERS:
        return None
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    if iqr == 0:
        return None
    return float(q1 - k * iqr), float(q3 + k * iqr)


def numeric_histogram(values: np.ndarray, is_integer: bool) -> dict[str, Any] | None:
    if values.size == 0:
        return None
    lo, hi = float(values.min()), float(values.max())
    distinct = np.unique(values)
    if is_integer and distinct.size <= 30:
        counts = [int((values == v).sum()) for v in distinct]
        return {"kind": "discrete", "values": [clean(v) for v in distinct], "counts": counts}
    if lo == hi:
        return {"kind": "bins", "edges": [lo, hi], "counts": [int(values.size)]}
    counts, edges = np.histogram(values, bins=HISTOGRAM_BINS, range=(lo, hi))
    return {"kind": "bins", "edges": [clean(e) for e in edges], "counts": counts.astype(int).tolist()}


def _numeric_profile(series: pd.Series, is_integer: bool) -> dict[str, Any]:
    values = series.dropna().to_numpy(dtype="float64")
    if values.size == 0:
        return {}
    quantiles = np.quantile(values, list(QUANTILES.values()))
    mask = mad_outlier_mask(values)
    fences = iqr_fences(values)
    return {
        "min": clean(values.min()),
        "max": clean(values.max()),
        "mean": clean(values.mean()),
        "median": clean(np.median(values)),
        "std": clean(values.std(ddof=1)) if values.size > 1 else None,
        "sum": clean(values.sum()),
        "quantiles": {k: clean(q) for k, q in zip(QUANTILES, quantiles, strict=True)},
        "iqr": clean(quantiles[4] - quantiles[2]),
        "zero_count": int((values == 0).sum()),
        "negative_count": int((values < 0).sum()),
        "outliers": {
            "iqr_count": None if fences is None else int(((values < fences[0]) | (values > fences[1])).sum()),
            "iqr_fences": None if fences is None else [clean(fences[0]), clean(fences[1])],
            "mad_count": None if mask is None else int(mask.sum()),
        },
        "histogram": numeric_histogram(values, is_integer),
    }


def _datetime_profile(series: pd.Series) -> dict[str, Any]:
    values = series.dropna()
    if values.empty:
        return {}
    lo, hi = values.min(), values.max()
    now = datetime.now(UTC)
    epoch = values.astype("int64").to_numpy() / 1e9  # seconds
    histogram: dict[str, Any] | None = None
    if lo != hi:
        counts, edges = np.histogram(epoch, bins=HISTOGRAM_BINS)
        histogram = {"kind": "time_bins",
                     "edges": [datetime.fromtimestamp(float(e), UTC).isoformat() for e in edges],
                     "counts": counts.astype(int).tolist()}
    return {
        "min": lo.isoformat(),
        "max": hi.isoformat(),
        "range_days": round((hi - lo).total_seconds() / 86400, 4),
        "future_count": int((values > pd.Timestamp(now + timedelta(days=1))).sum()),
        "pre_1971_count": int((values < pd.Timestamp("1971-01-01", tz="UTC")).sum()),
        "distinct_days": int(values.dt.floor("D").nunique()),
        "histogram": histogram,
    }


def _text_profile(raw: pd.Series) -> dict[str, Any]:
    values = raw.dropna().astype(str)
    if values.empty:
        return {}
    lengths = values.str.len()
    return {"length": {"min": int(lengths.min()), "max": int(lengths.max()), "mean": clean(lengths.mean())}}


def profile_column(name: str, raw: pd.Series, typed: pd.Series, inference: Any) -> dict[str, Any]:
    total = int(raw.size)
    non_null_raw = raw.dropna()
    null_count = total - int(non_null_raw.size)
    distinct = int(non_null_raw.nunique())
    non_null = int(non_null_raw.size)
    kind = inference.inferred_type
    counts = non_null_raw.astype(str).value_counts()
    is_categorical = (kind in ("string", "boolean") and 0 < distinct <= CATEGORICAL_MAX_DISTINCT
                      and (distinct / non_null <= CATEGORICAL_MAX_RATIO or non_null < 50))

    profile: dict[str, Any] = {
        "name": name,
        "type": kind,
        "non_null_count": non_null,
        "null_count": null_count,
        "null_pct": _pct(null_count, total),
        "distinct_count": distinct,
        "distinct_pct": _pct(distinct, non_null),
        "unique": non_null > 0 and distinct == non_null,
        "duplicate_value_count": non_null - distinct,
        "invalid_count": inference.invalid_count,
        "invalid_pct": _pct(inference.invalid_count, non_null),
        "invalid_examples": inference.invalid_examples,
        "is_constant": distinct == 1,
        "is_categorical": is_categorical,
        "mixed": inference.mixed,
        "notes": list(inference.notes),
        "top_values": [{"value": str(v), "count": int(c), "pct": _pct(int(c), non_null)}
                       for v, c in counts.head(10).items()],
    }
    if is_categorical:
        profile["categories"] = [{"value": str(v), "count": int(c), "pct": _pct(int(c), non_null)}
                                 for v, c in counts.items()]
    if kind in ("integer", "float"):
        profile.update(_numeric_profile(typed, kind == "integer"))
    elif kind == "datetime":
        profile.update(_datetime_profile(typed))
    elif kind == "boolean":
        values = typed.dropna()
        true_count = int(values.sum())
        profile.update({"true_count": true_count, "false_count": int(values.size - true_count),
                        "true_pct": _pct(true_count, int(values.size))})
    if kind in ("string", "boolean", "empty") or inference.invalid_count:
        profile.update(_text_profile(raw))
    if distinct == 1 and non_null:
        profile["notes"].append("Column has a single constant value.")
    return profile


def profile_table(table: LoadedTable) -> dict[str, Any]:
    raw, typed = table.raw, table.typed
    rows, cols = raw.shape
    duplicates = count_duplicate_rows(raw)
    missing = int(raw.isna().sum().sum())
    columns = [profile_column(inf.name, raw[inf.name], typed[inf.name], inf) for inf in table.inferences]
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "row_count": int(rows),
        "column_count": int(cols),
        "duplicate_rows": duplicates,
        "duplicate_pct": _pct(duplicates, rows),
        "missing_cells": missing,
        "missing_pct": _pct(missing, rows * cols),
        "exact": True,
        "notes": ["All statistics are exact over every row; histograms are binned summaries."],
        "columns": columns,
    }
