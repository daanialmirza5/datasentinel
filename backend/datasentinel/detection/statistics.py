"""Version-to-version statistical comparisons.

Every detector combines a significance test with a minimum *effect size*: with thousands of rows a
test detects differences far too small to matter, so a signal requires both p < ``alpha`` and a
practically meaningful change. Assumptions and safeguards per detector:

* **Missing / invalid value rates** — two-proportion z-test, or Fisher's exact test when any
  expected cell count is below 5. Rows are treated as independent Bernoulli trials.
* **Numeric distribution shift** — two-sample Kolmogorov–Smirnov test on non-missing values.
  Assumes independent samples from continuous distributions; on discrete data (e.g. small
  integers) the test is conservative, i.e. it under- rather than over-reports. PSI over the
  baseline's deciles is reported as an effect size.
* **Numeric outliers** — counts values outside the *baseline's* far-out Tukey fences
  (Q1 − 3·IQR, Q3 + 3·IQR) and tests the excess with a one-sided binomial test against the
  baseline's own far-out rate. Comparing against the baseline avoids flagging heavy tails that
  were always there.
* **Categories** — new values not seen in the baseline (count and share floors), baseline
  categories that disappeared, and a chi-square test of homogeneity over *baseline* categories
  (cells with expected count < 5 pooled) with PSI as effect size.
* **Row count / duplicates** — relative change threshold; two-proportion test for duplicate rate.

Columns with fewer than ``min_sample`` non-missing values on either side are not tested; the
comparison records ``insufficient_sample`` instead of guessing. With roughly 4 tests per column at
alpha = 0.001 the expected number of chance signals per comparison is about 0.004 × columns, before
the effect-size floors reduce it further.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from datasentinel.detection.signals import Signal
from datasentinel.profiling import clean
from datasentinel.services.datasets import LoadedTable

NUMERIC = {"integer", "float"}
EPS = 1e-4


@dataclass(frozen=True)
class DetectionConfig:
    alpha: float = 0.001
    min_sample: int = 30
    null_min_effect_pp: float = 2.0
    invalid_min_effect_pp: float = 0.5
    ks_min_statistic: float = 0.1
    psi_min: float = 0.1
    new_category_min_count: int = 5
    new_category_min_pct: float = 0.5
    missing_category_min_pct: float = 1.0
    row_count_change_pct: float = 20.0
    duplicate_min_effect_pp: float = 0.5
    outlier_iqr_k: float = 3.0
    outlier_min_excess: int = 3
    histogram_bins: int = 20

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def proportion_test(x1: int, n1: int, x2: int, n2: int) -> tuple[float, str]:
    """Two-sided test that two proportions are equal. Returns (p_value, test_name)."""
    if n1 == 0 or n2 == 0:
        return 1.0, "none"
    pooled = (x1 + x2) / (n1 + n2)
    if pooled in (0.0, 1.0):
        return 1.0, "none"
    expected = [n1 * pooled, n1 * (1 - pooled), n2 * pooled, n2 * (1 - pooled)]
    if min(expected) < 5:
        _, p = stats.fisher_exact([[x1, n1 - x1], [x2, n2 - x2]])
        return float(p), "fisher_exact"
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (x2 / n2 - x1 / n1) / se
    return float(2 * stats.norm.sf(abs(z))), "two_proportion_z"


def psi(base_props: np.ndarray, cand_props: np.ndarray) -> float:
    b = np.clip(base_props, EPS, None)
    c = np.clip(cand_props, EPS, None)
    return float(np.sum((c - b) * np.log(c / b)))


def numeric_psi(base: np.ndarray, cand: np.ndarray) -> float | None:
    edges = np.unique(np.quantile(base, np.linspace(0, 1, 11)))
    if edges.size < 3:
        return None
    edges[0], edges[-1] = -np.inf, np.inf
    b_counts = np.histogram(base, bins=edges)[0] / base.size
    c_counts = np.histogram(cand, bins=edges)[0] / cand.size
    return psi(b_counts, c_counts)


def _numeric_values(table: LoadedTable, column: str) -> np.ndarray:
    series = table.typed[column]
    if pd.api.types.is_bool_dtype(series):
        return np.array([], dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)


def _shared_histogram(base: np.ndarray, cand: np.ndarray, bins: int) -> dict[str, Any]:
    """Bins at the baseline's quantiles plus open tail bins below its minimum / above its maximum.

    Equal-width bins collapse when a few extreme values stretch the range; quantile bins keep the
    bulk readable (each holds ~1/bins of the baseline) and the tail bins show exactly how much of
    the candidate falls outside anything seen before.
    """
    edges = np.unique(np.quantile(base, np.linspace(0, 1, bins + 1)))
    if edges.size < 2:
        edges = np.array([edges[0], edges[0] + 1.0])
    below_b, below_c = (base < edges[0]).mean(), (cand < edges[0]).mean()
    above_b, above_c = (base > edges[-1]).mean(), (cand > edges[-1]).mean()
    inner_b = np.histogram(base[(base >= edges[0]) & (base <= edges[-1])], bins=edges)[0] / base.size
    inner_c = np.histogram(cand[(cand >= edges[0]) & (cand <= edges[-1])], bins=edges)[0] / cand.size
    return {
        "kind": "numeric",
        "binning": "baseline_quantiles_with_tails",
        "edges": [clean(e) for e in edges],
        "base": np.round(np.concatenate([[below_b], inner_b, [above_b]]), 6).tolist(),
        "candidate": np.round(np.concatenate([[below_c], inner_c, [above_c]]), 6).tolist(),
    }


def _severity_by(value: float, high: float, medium: float) -> str:
    return "high" if value >= high else "medium" if value >= medium else "low"


def _row_examples(
    table: LoadedTable, column: str, mask: np.ndarray, order: np.ndarray | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    positions = np.flatnonzero(mask)
    if order is not None and positions.size:
        positions = positions[np.argsort(-order[positions], kind="stable")]
    rows = table.raw.iloc[positions[:limit]]
    return [{"row": int(i) + 1, "value": rows.at[i, column]} for i in rows.index]


def compare_null_rates(
    column: str, base: LoadedTable, cand: LoadedTable, cfg: DetectionConfig, out: dict[str, Any], signals: list[Signal]
) -> None:
    n1, n2 = len(base.raw), len(cand.raw)
    x1, x2 = int(base.raw[column].isna().sum()), int(cand.raw[column].isna().sum())
    if n1 < cfg.min_sample or n2 < cfg.min_sample:
        out["null_rate"] = {"status": "insufficient_sample"}
        return
    p1, p2 = 100 * x1 / n1, 100 * x2 / n2
    p_value, test = proportion_test(x1, n1, x2, n2)
    delta = p2 - p1
    out["null_rate"] = {
        "base_pct": round(p1, 4),
        "candidate_pct": round(p2, 4),
        "delta_pp": round(delta, 4),
        "p_value": p_value,
        "test": test,
    }
    if p_value < cfg.alpha and abs(delta) >= cfg.null_min_effect_pp:
        if delta > 0:
            severity = _severity_by(delta, 20, 5)
            signals.append(
                Signal(
                    "null_rate_increase",
                    severity,
                    f"Missing '{column}' values rose {p1:.1f}% → {p2:.1f}%",
                    f"The share of missing values in '{column}' increased by {delta:.1f} percentage points "
                    f"({test}, p={p_value:.2g}). Aggregates computed over this column will silently cover fewer rows.",
                    column,
                    evidence=out["null_rate"],
                )
            )
        else:
            signals.append(
                Signal(
                    "null_rate_decrease",
                    "info",
                    f"Missing '{column}' values fell {p1:.1f}% → {p2:.1f}%",
                    f"Fewer missing values in '{column}' ({test}, p={p_value:.2g}). Usually good news, but confirm that "
                    "defaults are not being filled in upstream.",
                    column,
                    evidence=out["null_rate"],
                )
            )


def compare_invalid(
    column: str,
    kind: str,
    base: LoadedTable,
    cand: LoadedTable,
    cfg: DetectionConfig,
    out: dict[str, Any],
    signals: list[Signal],
) -> None:
    b_inf, c_inf = base.inference(column), cand.inference(column)
    if b_inf is None or c_inf is None:
        return
    n1, n2 = b_inf.non_null_count, c_inf.non_null_count
    if n1 < cfg.min_sample or n2 < cfg.min_sample:
        return
    x1, x2 = b_inf.invalid_count, c_inf.invalid_count
    p_value, test = proportion_test(x1, n1, x2, n2)
    delta = 100 * (x2 / n2 - x1 / n1)
    out["invalid_values"] = {
        "base": x1,
        "candidate": x2,
        "delta_pp": round(delta, 4),
        "p_value": p_value,
        "examples": c_inf.invalid_examples,
    }
    if p_value < cfg.alpha and delta >= cfg.invalid_min_effect_pp:
        category = "timestamp_invalid" if kind == "datetime" else "invalid_values"
        noun = "unparseable timestamps" if kind == "datetime" else f"values that are not valid {kind}"
        signals.append(
            Signal(
                category,
                _severity_by(delta, 5, 1),
                f"'{column}' has {x2} {noun}",
                f"{x2} of {n2} non-missing values in '{column}' are {noun} (previously {x1} of {n1}; {test}, "
                f"p={p_value:.2g}). Examples: {', '.join(repr(e) for e in c_inf.invalid_examples[:3])}.",
                column,
                evidence=out["invalid_values"],
            )
        )


def compare_numeric(
    column: str, base: LoadedTable, cand: LoadedTable, cfg: DetectionConfig, out: dict[str, Any], signals: list[Signal]
) -> None:
    b, c = _numeric_values(base, column), _numeric_values(cand, column)
    out["base"] = _summary(b)
    out["candidate"] = _summary(c)
    if b.size < cfg.min_sample or c.size < cfg.min_sample:
        out["distribution"] = {"status": "insufficient_sample"}
        return
    out["chart"] = _shared_histogram(b, c, cfg.histogram_bins)

    ks = stats.ks_2samp(b, c)
    psi_value = numeric_psi(b, c)
    std = float(b.std(ddof=1)) if b.size > 1 else 0.0
    mean_shift = (float(c.mean()) - float(b.mean())) / std if std > 0 else None
    out["distribution"] = {
        "ks_statistic": float(ks.statistic),
        "p_value": float(ks.pvalue),
        "psi": psi_value,
        "mean_shift_in_std": mean_shift,
        "std_ratio": float(c.std(ddof=1)) / std if std > 0 and c.size > 1 else None,
    }
    if ks.pvalue < cfg.alpha and ks.statistic >= cfg.ks_min_statistic:
        signals.append(
            Signal(
                "distribution_shift",
                _severity_by(float(ks.statistic), 0.3, 0.2),
                f"'{column}' distribution shifted (KS D={ks.statistic:.2f})",
                f"The distribution of '{column}' differs from the previous version (two-sample KS D={ks.statistic:.3f}, "
                f"p={ks.pvalue:.2g}; PSI={psi_value if psi_value is None else round(psi_value, 3)}; mean moved "
                f"{'n/a' if mean_shift is None else f'{mean_shift:+.2f}'} baseline standard deviations).",
                column,
                evidence=out["distribution"],
            )
        )

    q1, q3 = np.percentile(b, [25, 75])
    iqr = q3 - q1
    lo, hi = (q1 - cfg.outlier_iqr_k * iqr, q3 + cfg.outlier_iqr_k * iqr) if iqr > 0 else (b.min(), b.max())
    base_out = int(((b < lo) | (b > hi)).sum())
    rate = max(base_out / b.size, 0.5 / b.size)
    cand_numbers = (
        pd.to_numeric(cand.typed[column], errors="coerce").to_numpy(dtype=float)
        if not pd.api.types.is_bool_dtype(cand.typed[column])
        else np.full(len(cand.raw), np.nan)
    )
    mask = (cand_numbers < lo) | (cand_numbers > hi)
    cand_out = int(mask.sum())
    expected = rate * c.size
    p_value = float(stats.binom.sf(cand_out - 1, c.size, rate)) if cand_out else 1.0
    distance = np.nan_to_num(np.maximum(lo - cand_numbers, cand_numbers - hi), nan=-np.inf)
    out["outliers"] = {
        "fences": [clean(lo), clean(hi)],
        "base_count": base_out,
        "candidate_count": cand_out,
        "expected": round(expected, 3),
        "p_value": p_value,
    }
    if p_value < cfg.alpha and cand_out - expected >= cfg.outlier_min_excess:
        pct = 100 * cand_out / c.size
        out["outliers"]["examples"] = _row_examples(cand, column, mask, distance)
        signals.append(
            Signal(
                "numeric_outlier",
                "high" if pct >= 1 else "medium",
                f"{cand_out} extreme '{column}' values (expected ≈{expected:.1f})",
                f"{cand_out} values of '{column}' ({pct:.2f}%) fall outside the previous version's far-out fences "
                f"[{lo:.4g}, {hi:.4g}] versus ≈{expected:.1f} expected from the baseline rate (binomial p={p_value:.2g}). "
                "Typical causes: unit or scaling errors, sentinel values, corrupted parsing.",
                column,
                evidence=out["outliers"],
            )
        )


def _summary(values: np.ndarray) -> dict[str, Any]:
    if values.size == 0:
        return {"count": 0}
    return {
        "count": int(values.size),
        "mean": clean(values.mean()),
        "median": clean(np.median(values)),
        "std": clean(values.std(ddof=1)) if values.size > 1 else None,
        "min": clean(values.min()),
        "max": clean(values.max()),
    }


def compare_categories(
    column: str, base: LoadedTable, cand: LoadedTable, cfg: DetectionConfig, out: dict[str, Any], signals: list[Signal]
) -> None:
    b = base.raw[column].dropna().astype(str)
    c = cand.raw[column].dropna().astype(str)
    b_counts, c_counts = b.value_counts(), c.value_counts()
    labels = list(dict.fromkeys([*b_counts.index[:15], *c_counts.index[:15]]))
    out["chart"] = {
        "kind": "categorical",
        "labels": labels,
        "base": [round(float(b_counts.get(k, 0)) / max(b.size, 1), 6) for k in labels],
        "candidate": [round(float(c_counts.get(k, 0)) / max(c.size, 1), 6) for k in labels],
    }
    if b.size < cfg.min_sample or c.size < cfg.min_sample:
        out["categories"] = {"status": "insufficient_sample"}
        return
    known = set(b_counts.index)
    new_counts = c_counts[~c_counts.index.isin(known)]
    new_rows = int(new_counts.sum())
    new_pct = 100 * new_rows / c.size
    missing = [k for k, v in b_counts.items() if 100 * v / b.size >= cfg.missing_category_min_pct and k not in c_counts]

    # Mix change among baseline categories only (new values are reported separately).
    c_known = c_counts[c_counts.index.isin(known)].reindex(b_counts.index, fill_value=0)
    chi_p, psi_value = 1.0, 0.0
    if c_known.sum() >= cfg.min_sample:
        b_arr, c_arr = b_counts.to_numpy(dtype=float), c_known.to_numpy(dtype=float)
        psi_value = psi(b_arr / b_arr.sum(), c_arr / c_arr.sum())
        totals = b_arr + c_arr
        expected_min = np.minimum(totals * b_arr.sum() / totals.sum(), totals * c_arr.sum() / totals.sum())
        keep = expected_min >= 5
        table = np.vstack([b_arr[keep], c_arr[keep]])
        if (~keep).any():
            table = np.hstack([table, [[b_arr[~keep].sum()], [c_arr[~keep].sum()]]])
        table = table[:, table.sum(axis=0) > 0]
        if table.shape[1] >= 2:
            chi_p = float(stats.chi2_contingency(table, correction=False)[1])
    out["categories"] = {
        "new_values": {str(k): int(v) for k, v in new_counts.head(20).items()},
        "new_rows": new_rows,
        "new_pct": round(new_pct, 4),
        "missing_values": missing[:20],
        "chi2_p_value": chi_p,
        "psi": round(psi_value, 6),
    }

    if new_rows >= cfg.new_category_min_count and new_pct >= cfg.new_category_min_pct:
        top = ", ".join(f"'{k}' ({v})" for k, v in new_counts.head(5).items())
        signals.append(
            Signal(
                "new_category",
                "high" if new_pct >= 5 else "medium",
                f"Unexpected values in '{column}': {top}",
                f"{new_rows} rows ({new_pct:.2f}%) of '{column}' contain values never seen in the previous version: {top}. "
                "Joins, mappings and group-bys keyed on this column may drop or mislabel these rows.",
                column,
                evidence=out["categories"],
            )
        )
    if missing:
        signals.append(
            Signal(
                "category_missing",
                "low",
                f"Categories disappeared from '{column}'",
                f"Values that made up at least {cfg.missing_category_min_pct}% of '{column}' are absent: "
                f"{', '.join(repr(m) for m in missing[:5])}. Check for upstream filtering or remapping.",
                column,
                evidence={"missing_values": missing[:20]},
            )
        )
    if chi_p < cfg.alpha and psi_value >= cfg.psi_min:
        signals.append(
            Signal(
                "category_frequency_shift",
                "medium" if psi_value >= 0.25 else "low",
                f"Category mix of '{column}' changed (PSI={psi_value:.2f})",
                f"The relative frequencies of existing '{column}' values changed (chi-square p={chi_p:.2g}, "
                f"PSI={psi_value:.3f}).",
                column,
                evidence=out["categories"],
            )
        )


def compare_uniqueness(
    column: str, base: LoadedTable, cand: LoadedTable, cfg: DetectionConfig, out: dict[str, Any], signals: list[Signal]
) -> None:
    b = base.raw[column].dropna()
    c = cand.raw[column].dropna()
    if b.size < cfg.min_sample or c.size < cfg.min_sample:
        return
    if b.nunique() == b.size:
        duplicated = c.duplicated(keep="first")
        count = int(duplicated.sum())
        out["uniqueness"] = {"base_unique": True, "candidate_duplicates": count}
        if count:
            examples = c[duplicated].astype(str).value_counts().head(5)
            signals.append(
                Signal(
                    "uniqueness_lost",
                    "high",
                    f"'{column}' is no longer unique ({count} repeats)",
                    f"Every value of '{column}' was unique in the previous version; now {count} values repeat "
                    f"(e.g. {', '.join(repr(k) for k in examples.index)}). If this is a key, joins will fan out.",
                    column,
                    evidence={**out["uniqueness"], "examples": {str(k): int(v) for k, v in examples.items()}},
                )
            )


def compare_timestamps(
    column: str,
    base_profile: dict[str, Any],
    cand_profile: dict[str, Any],
    cfg: DetectionConfig,
    out: dict[str, Any],
    signals: list[Signal],
) -> None:
    n1, n2 = base_profile.get("non_null_count", 0), cand_profile.get("non_null_count", 0)
    if n1 < cfg.min_sample or n2 < cfg.min_sample:
        return
    x1 = base_profile.get("future_count", 0) + base_profile.get("pre_1971_count", 0)
    x2 = cand_profile.get("future_count", 0) + cand_profile.get("pre_1971_count", 0)
    rate = max(x1 / n1, 0.5 / n1)
    p_value = float(stats.binom.sf(x2 - 1, n2, rate)) if x2 else 1.0
    out["window"] = {
        "base": [base_profile.get("min"), base_profile.get("max")],
        "candidate": [cand_profile.get("min"), cand_profile.get("max")],
        "implausible_base": x1,
        "implausible_candidate": x2,
        "p_value": p_value,
    }
    if p_value < cfg.alpha and x2 - rate * n2 >= cfg.outlier_min_excess:
        signals.append(
            Signal(
                "timestamp_out_of_range",
                "high",
                f"{x2} implausible '{column}' timestamps",
                f"{x2} values of '{column}' lie in the future or before 1971 (previously {x1}); typical of default "
                "epoch values, time-zone bugs or swapped day/month fields.",
                column,
                evidence=out["window"],
            )
        )


def compare_dataset(
    base: LoadedTable,
    cand: LoadedTable,
    base_profile: dict[str, Any],
    cand_profile: dict[str, Any],
    cfg: DetectionConfig,
    signals: list[Signal],
) -> dict[str, Any]:
    n1, n2 = len(base.raw), len(cand.raw)
    change = 100 * (n2 - n1) / n1 if n1 else None
    row_info: dict[str, Any] = {"base": n1, "candidate": n2, "change_pct": None if change is None else round(change, 4)}
    if change is not None and abs(change) >= cfg.row_count_change_pct:
        direction = "dropped" if change < 0 else "grew"
        signals.append(
            Signal(
                "row_count_change",
                "high" if abs(change) >= 50 else "medium",
                f"Row count {direction} {abs(change):.1f}% ({n1} → {n2})",
                f"The new version has {n2} rows versus {n1} ({change:+.1f}%), beyond the ±{cfg.row_count_change_pct}% "
                "tolerance. Check for partial loads, upstream filters or duplicated batches.",
                None,
                evidence=row_info,
            )
        )
    d1, d2 = base_profile.get("duplicate_rows", 0), cand_profile.get("duplicate_rows", 0)
    dup: dict[str, Any] = {"base": d1, "candidate": d2}
    if n1 >= cfg.min_sample and n2 >= cfg.min_sample:
        p_value, test = proportion_test(d1, n1, d2, n2)
        delta = 100 * (d2 / n2 - d1 / n1)
        dup.update({"delta_pp": round(delta, 4), "p_value": p_value, "test": test})
        if p_value < cfg.alpha and delta >= cfg.duplicate_min_effect_pp:
            signals.append(
                Signal(
                    "duplicate_rows",
                    "high" if delta >= 5 else "medium",
                    f"{d2} fully duplicated rows (was {d1})",
                    f"{d2} rows ({100 * d2 / n2:.2f}%) are exact copies of an earlier row versus {d1} before ({test}, "
                    f"p={p_value:.2g}). Replayed batches inflate counts and sums downstream.",
                    None,
                    evidence=dup,
                )
            )
    return {"row_count": row_info, "duplicates": dup}


_IDENTIFIER_NAME = re.compile(r"(?i)(^id$|_id$|^id_|uuid|guid|_key$|^key$)")


def is_identifier(name: str, profile: dict[str, Any], min_sample: int) -> bool:
    """Identifier columns hold labels, not measurements, so their distributions are not compared.

    A column is treated as an identifier when its name looks like a key (``id``, ``*_id``, ``uuid``,
    ``*_key``) or when it is an integer/string column whose baseline values are all distinct.
    """
    if _IDENTIFIER_NAME.search(name):
        return True
    return (
        profile.get("type") in ("integer", "string")
        and bool(profile.get("unique"))
        and profile.get("non_null_count", 0) >= min_sample
    )


def compare_columns(
    base: LoadedTable,
    cand: LoadedTable,
    base_profile: dict[str, Any],
    cand_profile: dict[str, Any],
    cfg: DetectionConfig,
    signals: list[Signal],
) -> list[dict[str, Any]]:
    b_prof = {c["name"]: c for c in base_profile.get("columns", [])}
    c_prof = {c["name"]: c for c in cand_profile.get("columns", [])}
    comparisons = []
    for inference in base.inferences:
        column = inference.name
        cand_inf = cand.inference(column)
        if cand_inf is None:
            continue
        b_type, c_type = inference.inferred_type, cand_inf.inferred_type
        identifier = is_identifier(column, b_prof.get(column, {}), cfg.min_sample)
        out: dict[str, Any] = {
            "column": column,
            "base_type": b_type,
            "candidate_type": c_type,
            "identifier": identifier,
            "base_null_pct": b_prof.get(column, {}).get("null_pct"),
            "candidate_null_pct": c_prof.get(column, {}).get("null_pct"),
        }
        compare_null_rates(column, base, cand, cfg, out, signals)
        if b_type == c_type and b_type != "string" and b_type != "empty":
            compare_invalid(column, b_type, base, cand, cfg, out, signals)
        if identifier:
            out["distribution"] = {
                "status": "skipped_identifier",
                "reason": "Identifier values are labels; their distribution is not compared.",
            }
        elif b_type in NUMERIC and c_type in NUMERIC:
            compare_numeric(column, base, cand, cfg, out, signals)
        elif b_prof.get(column, {}).get("is_categorical"):
            compare_categories(column, base, cand, cfg, out, signals)
        elif b_type == "datetime" and c_type == "datetime":
            compare_timestamps(column, b_prof[column], c_prof[column], cfg, out, signals)
        if b_type in ("integer", "string"):
            compare_uniqueness(column, base, cand, cfg, out, signals)
        comparisons.append(out)
    return comparisons
