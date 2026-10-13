"""Anomalies *within* a single version (no baseline required).

* **Numeric outliers** — modified z-score |0.6745·(x − median)/MAD| > 3.5 (Iglewicz & Hoaglin).
  Robust to the outliers themselves, unlike the mean/standard-deviation z-score. Strictly positive,
  right-skewed columns (sample skewness > 1, e.g. prices, amounts) are scored on the log scale,
  where multiplicative data is roughly symmetric. When MAD is zero (more than half the values
  identical) Tukey's far-out fences (3 × IQR) are used instead; when both spreads are zero the
  column is skipped. Needs at least 8 values. If a method would flag more than 5% of a column, the
  column is reported as *not applicable* rather than as outliers (zero-inflated, heavy-tailed or
  multi-modal data violates the method's assumption that outliers are rare). Outliers in a single
  version are often legitimate (large orders, real spikes) and are reported at *low* severity.
* **Time-series deviations** — when a datetime column spans at least 14 distinct days, rows are
  bucketed per UTC day and the daily row count and daily mean of each numeric column are scored
  with the same robust z-score across days. Days with |z| > 3.5 are reported. The most complete
  timestamp column is used, and the first and last day (usually partial buckets) are not scored.
  Days need a median of at least 10 rows; sparser data is not scored because a daily mean of one or
  two rows is noise, not a trend. Seasonality is not
  modelled, so strongly weekly-periodic data may produce weekday signals — documented limitation.
* **Isolation Forest (optional)** — multivariate, unsupervised; only runs when scikit-learn is
  installed. Uses a fixed random seed, robust-scaled numeric columns and median imputation. It
  ranks unusual *rows*; it is never required for the core detectors and is not part of the
  benchmark's headline metrics.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from datasentinel.detection.signals import Signal, sort_signals
from datasentinel.detection.statistics import is_identifier
from datasentinel.profiling import MAD_THRESHOLD, clean
from datasentinel.services.datasets import LoadedTable

MIN_VALUES = 8
MIN_DAYS = 14
MAX_TS_METRICS = 8
ML_MIN_ROWS = 50
ML_MAX_ROWS = 100_000
SKEW_FOR_LOG = 1.0
MIN_ROWS_PER_DAY = 10
MAX_OUTLIER_PCT = 5.0


def _robust_z(values: np.ndarray) -> np.ndarray | None:
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        return None
    return 0.6745 * (values - median) / mad


def _measure_columns(table: LoadedTable, profile: dict[str, Any]) -> list[str]:
    profiles = {c["name"]: c for c in profile.get("columns", [])}
    return [
        inf.name
        for inf in table.inferences
        if inf.inferred_type in ("integer", "float") and not is_identifier(inf.name, profiles.get(inf.name, {}), 30)
    ]


def numeric_outliers(table: LoadedTable, profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (outliers, not_applicable). See the module docstring for the method and safeguards."""
    results, skipped = [], []
    for column in _measure_columns(table, profile):
        series = table.typed[column].astype("float64")
        valid = series.notna().to_numpy()
        values = series.to_numpy()[valid]
        if values.size < MIN_VALUES:
            continue
        scale = "linear"
        scored = values
        if values.min() > 0 and values.size > 2 and float(pd.Series(values).skew()) > SKEW_FOR_LOG:
            scored, scale = np.log(values), "log"
        z = _robust_z(scored)
        method = f"modified_z (MAD, {scale} scale)"
        if z is not None:
            mask = np.abs(z) > MAD_THRESHOLD
            score = np.abs(z)
        else:
            q1, q3 = np.percentile(scored, [25, 75])
            iqr = q3 - q1
            if iqr == 0:
                continue
            lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
            mask = (scored < lo) | (scored > hi)
            score = np.maximum(lo - scored, scored - hi) / iqr
            method = f"tukey_far_out (3 x IQR, {scale} scale)"
        count = int(mask.sum())
        if not count:
            continue
        pct = 100 * count / values.size
        if pct > MAX_OUTLIER_PCT:
            skipped.append(
                {
                    "column": column,
                    "method": method,
                    "flagged_pct": round(pct, 2),
                    "reason": f"The method would flag {pct:.1f}% of values; outliers are rare by definition, so the "
                    "distribution (heavy-tailed, zero-inflated or multi-modal) is not suited to this test.",
                }
            )
            continue
        positions = np.flatnonzero(valid)[mask]
        order = np.argsort(-score[mask], kind="stable")[:5]
        examples = [
            {
                "row": int(positions[i]) + 1,
                "value": table.raw.iat[int(positions[i]), table.raw.columns.get_loc(column)],
                "score": round(float(score[mask][i]), 3),
            }
            for i in order
        ]
        results.append(
            {
                "column": column,
                "method": method,
                "threshold": MAD_THRESHOLD if z is not None else 3.0,
                "count": count,
                "pct": round(pct, 4),
                "median": clean(np.median(values)),
                "examples": examples,
            }
        )
    return results, skipped


def time_series_deviations(table: LoadedTable, profile: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        c for c in profile.get("columns", []) if c["type"] == "datetime" and c.get("distinct_days", 0) >= MIN_DAYS
    ]
    if not candidates:
        return None
    # Prefer the most complete timestamp (e.g. order time over ship time), then the longest span.
    ts_column = max(candidates, key=lambda c: (c["non_null_count"], c["distinct_days"]))["name"]
    days = table.typed[ts_column].dt.floor("D")
    frame = pd.DataFrame({"day": days})
    metrics = _measure_columns(table, profile)[:MAX_TS_METRICS]
    for column in metrics:
        frame[column] = table.typed[column].astype("float64")
    frame = frame.dropna(subset=["day"])
    grouped = frame.groupby("day")
    daily = pd.DataFrame({"row_count": grouped.size()})
    for column in metrics:
        daily[f"mean({column})"] = grouped[column].mean()
    daily = daily.sort_index()
    # The first and last day are usually partial buckets (an export starting or ending mid-day, or
    # events spilling past the extract window); they are charted but never scored.
    scored_days = daily.iloc[1:-1]
    deviations: list[dict[str, Any]] = []
    median_rows = float(daily["row_count"].median()) if len(daily) else 0.0
    if median_rows < MIN_ROWS_PER_DAY:
        return {
            "column": ts_column,
            "days": len(daily),
            "metrics_checked": [],
            "deviations": [],
            "series": {
                "row_count": [{"date": d.date().isoformat(), "value": clean(v)} for d, v in daily["row_count"].items()]
            },
            "skipped": f"Only {median_rows:g} rows per day (median); daily aggregates need at least {MIN_ROWS_PER_DAY} "
            "to be stable, so no day was scored.",
        }
    checked = []
    for metric in daily.columns:
        values = scored_days[metric].to_numpy(dtype=float)
        valid = ~np.isnan(values)
        if valid.sum() < MIN_DAYS:
            continue
        z = _robust_z(values[valid])
        if z is None:
            continue
        checked.append(metric)
        median = float(np.median(values[valid]))
        for day, value, score in zip(scored_days.index[valid], values[valid], z, strict=True):
            if abs(score) > MAD_THRESHOLD:
                deviations.append(
                    {
                        "date": day.date().isoformat(),
                        "metric": metric,
                        "value": clean(value),
                        "median": clean(median),
                        "robust_z": round(float(score), 3),
                    }
                )
    flagged_metrics = sorted({d["metric"] for d in deviations})
    series = {
        metric: [{"date": d.date().isoformat(), "value": clean(v)} for d, v in daily[metric].items()]
        for metric in ["row_count", *flagged_metrics]
    }
    return {
        "column": ts_column,
        "days": len(daily),
        "metrics_checked": checked,
        "deviations": deviations,
        "series": series,
    }


def isolation_forest(table: LoadedTable, profile: dict[str, Any], seed: int = 0) -> dict[str, Any]:
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return {"available": False, "reason": "scikit-learn is not installed (pip install -r requirements-ml.txt)."}
    columns = _measure_columns(table, profile)
    if len(columns) < 2 or len(table.raw) < ML_MIN_ROWS:
        return {
            "available": True,
            "ran": False,
            "reason": f"Needs at least 2 numeric measure columns and {ML_MIN_ROWS} rows.",
        }
    data = table.typed[columns].astype("float64")
    if len(data) > ML_MAX_ROWS:
        return {"available": True, "ran": False, "reason": f"More than {ML_MAX_ROWS} rows; skipped to bound runtime."}
    medians = data.median()
    q1, q3 = data.quantile(0.25), data.quantile(0.75)
    scale = (q3 - q1).replace(0, np.nan).fillna(data.std(ddof=0)).replace(0, 1.0)
    scaled = ((data.fillna(medians) - medians) / scale).to_numpy()
    model = IsolationForest(n_estimators=200, contamination="auto", random_state=seed)
    labels = model.fit_predict(scaled)
    scores = -model.score_samples(scaled)
    top = np.argsort(-scores, kind="stable")[:10]
    return {
        "available": True,
        "ran": True,
        "columns": columns,
        "seed": seed,
        "rows": len(data),
        "outlier_count": int((labels == -1).sum()),
        "top_rows": [
            {
                "row": int(i) + 1,
                "score": round(float(scores[i]), 4),
                "values": {c: table.raw.iat[int(i), table.raw.columns.get_loc(c)] for c in columns},
            }
            for i in top
        ],
        "note": "Isolation Forest scores rank unusual rows; they are not calibrated probabilities of error.",
    }


def detect_within_version(table: LoadedTable, profile: dict[str, Any], include_ml: bool = False) -> dict[str, Any]:
    outliers, not_applicable = numeric_outliers(table, profile)
    ts = time_series_deviations(table, profile)
    signals: list[Signal] = []
    for item in outliers:
        signals.append(
            Signal(
                "numeric_outlier",
                "low",
                f"{item['count']} outlying '{item['column']}' values ({item['pct']:.2f}%)",
                f"{item['count']} values of '{item['column']}' are far from the median ({item['method']}). Outliers within "
                "a single version can be legitimate; compare with previous versions before acting.",
                item["column"],
                "statistics",
                item,
            )
        )
    if ts:
        for deviation in ts["deviations"]:
            signals.append(
                Signal(
                    "time_series_deviation",
                    "medium",
                    f"{deviation['metric']} on {deviation['date']} deviates (robust z={deviation['robust_z']:+.1f})",
                    f"On {deviation['date']} the daily {deviation['metric']} was {deviation['value']:.4g} versus a median of "
                    f"{deviation['median']:.4g} across {ts['days']} days (robust z={deviation['robust_z']:+.1f}).",
                    ts["column"],
                    "time_series",
                    deviation,
                )
            )
    return {
        "outliers": outliers,
        "outliers_not_applicable": not_applicable,
        "time_series": ts,
        "ml": isolation_forest(table, profile) if include_ml else None,
        "signals": sort_signals([s.as_dict() for s in signals]),
    }
