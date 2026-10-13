"""Controlled, reproducible fault injection.

Every injector receives the *original* parsed table (never mutated), a seeded ``numpy`` random
generator and validated parameters, and returns a modified copy of the string table plus the
**ground truth** describing exactly what was changed. The ground truth is stored with the
experiment for evaluation and is never passed to the detection pipeline.

Ground truth fields:
    fault_type, params (resolved, including the chosen column), scope ("column" | "dataset"),
    affected_columns, affected_rows, expected.primary (signal categories that *should* fire),
    expected.accepted (consequential categories that are not false positives), examples.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from datasentinel.detection.statistics import is_identifier
from datasentinel.services.datasets import LoadedTable


class FaultError(ValueError):
    pass


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str | None = Field(default=None, max_length=128)


class MissingValuesParams(_Params):
    fraction: float = Field(default=0.10, gt=0, le=1)


class DuplicateParams(_Params):
    fraction: float = Field(default=0.05, gt=0, le=1)


class OutlierParams(_Params):
    fraction: float = Field(default=0.02, gt=0, le=0.5)
    factor: float = Field(default=50.0, description="Multiplier applied to the selected values (|factor| >= 2).")


class TypeChangeParams(_Params):
    fraction: float = Field(default=1.0, gt=0, le=1)
    suffix: str = Field(default=" USD", min_length=1, max_length=20)


class ColumnRemovalParams(_Params):
    pass


class CategoryParams(_Params):
    fraction: float = Field(default=0.05, gt=0, le=1)
    values: list[str] = Field(default_factory=lambda: ["UNKNOWN_CODE"], min_length=1, max_length=10)


class RowReductionParams(_Params):
    fraction: float = Field(default=0.40, gt=0, lt=1, description="Share of rows removed.")


class TimestampParams(_Params):
    fraction: float = Field(default=0.03, gt=0, le=1)
    mode: Literal["mixed", "unparseable", "epoch", "future"] = "mixed"


class ReferentialParams(_Params):
    fraction: float = Field(default=0.05, gt=0, le=1)


class ShiftParams(_Params):
    shift_std: float = Field(default=1.0, description="Shift added to every value, in baseline standard deviations.")
    scale: float = Field(default=1.0, gt=0, description="Multiplicative spread change around the mean.")


@dataclass
class FaultContext:
    table: LoadedTable
    profile: dict[str, Any]
    rng: np.random.Generator
    foreign_key_columns: list[str]


@dataclass
class FaultType:
    key: str
    label: str
    description: str
    params_model: type[_Params]
    column_kind: str | None  # numeric | categorical | datetime | any | key | None
    primary: list[str]
    accepted: list[str]
    injector: Callable[[FaultContext, Any], tuple[pd.DataFrame, dict[str, Any]]]
    note: str = ""


def _profiles(ctx: FaultContext) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in ctx.profile.get("columns", [])}


def eligible_columns(ctx: FaultContext, kind: str) -> list[str]:
    profiles = _profiles(ctx)
    columns = []
    for inference in ctx.table.inferences:
        name, prof = inference.name, profiles.get(inference.name, {})
        kind_of = inference.inferred_type
        if kind == "numeric":
            ok = kind_of in ("integer", "float") and not is_identifier(name, prof, 30) and (prof.get("std") or 0) > 0
        elif kind == "categorical":
            ok = bool(prof.get("is_categorical")) and kind_of == "string"
        elif kind == "datetime":
            ok = kind_of == "datetime"
        elif kind == "key":
            ok = name in ctx.foreign_key_columns
        else:
            ok = kind_of != "empty"
        if ok:
            columns.append(name)
    return columns


def _pick_column(ctx: FaultContext, params: _Params, kind: str) -> str:
    eligible = eligible_columns(ctx, kind)
    if params.column:
        if params.column not in ctx.table.raw.columns:
            raise FaultError(f"Column '{params.column}' does not exist in the base version.")
        if params.column not in eligible:
            raise FaultError(
                f"Column '{params.column}' is not suitable for this fault (needs a {kind} column). "
                f"Eligible: {', '.join(eligible) or 'none'}."
            )
        return params.column
    if not eligible:
        raise FaultError(f"The base version has no {kind} column suitable for this fault.")
    return str(eligible[int(ctx.rng.integers(0, len(eligible)))])


def _choose_rows(ctx: FaultContext, candidates: np.ndarray, fraction: float, minimum: int = 1) -> np.ndarray:
    if candidates.size == 0:
        raise FaultError("No rows are available to modify.")
    count = min(candidates.size, max(minimum, round(candidates.size * fraction)))
    return np.sort(ctx.rng.choice(candidates, size=count, replace=False))


def _fmt_number(value: float, integer: bool) -> str:
    return str(round(float(value))) if integer else format(float(value), ".10g")


def _examples(before: pd.DataFrame, after: pd.DataFrame, positions: np.ndarray, column: str, limit: int = 10):
    return [
        {
            "row": int(p) + 1,
            "before": {column: before.iat[int(p), before.columns.get_loc(column)]},
            "after": {column: after.iat[int(p), after.columns.get_loc(column)]},
        }
        for p in positions[:limit]
    ]


def _truth(
    fault: str,
    params: _Params,
    scope: str,
    columns: list[str],
    rows: int,
    primary: list[str],
    accepted: list[str],
    examples: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "fault_type": fault,
        "params": params.model_dump(),
        "scope": scope,
        "affected_columns": columns,
        "affected_rows": int(rows),
        "expected": {"primary": primary, "accepted": accepted},
        "examples": examples,
        **extra,
    }


# ---------------------------------------------------------------- injectors


def inject_missing(ctx: FaultContext, p: MissingValuesParams):
    column = p.column = _pick_column(ctx, p, "any")
    out = ctx.table.raw.copy()
    rows = _choose_rows(ctx, np.flatnonzero(out[column].notna().to_numpy()), p.fraction)
    out.iloc[rows, out.columns.get_loc(column)] = None
    return out, _truth(
        "missing_values",
        p,
        "column",
        [column],
        rows.size,
        ["null_rate_increase"],
        ["nullability_change", "uniqueness_lost"],
        _examples(ctx.table.raw, out, rows, column),
    )


def inject_duplicates(ctx: FaultContext, p: DuplicateParams):
    base = ctx.table.raw
    sources = _choose_rows(ctx, np.arange(len(base)), p.fraction)
    copies = base.iloc[sources]
    positions = ctx.rng.integers(0, len(base) + 1, size=len(copies))
    order = np.argsort(np.concatenate([np.arange(len(base)) + 0.5, positions]), kind="stable")
    out = pd.concat([base, copies], ignore_index=True).iloc[order].reset_index(drop=True)
    return out, _truth(
        "duplicate_records",
        p,
        "dataset",
        [],
        len(copies),
        ["duplicate_rows"],
        ["uniqueness_lost", "row_count_change"],
        [{"row": int(s) + 1, "note": "row duplicated"} for s in sources[:10]],
    )


def inject_outliers(ctx: FaultContext, p: OutlierParams):
    if abs(p.factor) < 2:
        raise FaultError("factor must be at least 2 in absolute value to create outliers.")
    column = p.column = _pick_column(ctx, p, "numeric")
    out = ctx.table.raw.copy()
    typed = ctx.table.typed[column].astype("float64")
    rows = _choose_rows(ctx, np.flatnonzero(typed.notna().to_numpy()), p.fraction, minimum=3)
    integer = ctx.table.inference(column).inferred_type == "integer"
    col = out.columns.get_loc(column)
    for r in rows:
        out.iat[int(r), col] = _fmt_number(typed.iat[int(r)] * p.factor, integer)
    return out, _truth(
        "numeric_outliers",
        p,
        "column",
        [column],
        rows.size,
        ["numeric_outlier"],
        ["distribution_shift", "range_violation"],
        _examples(ctx.table.raw, out, rows, column),
    )


def inject_type_change(ctx: FaultContext, p: TypeChangeParams):
    column = p.column = _pick_column(ctx, p, "numeric")
    out = ctx.table.raw.copy()
    rows = _choose_rows(ctx, np.flatnonzero(out[column].notna().to_numpy()), p.fraction)
    col = out.columns.get_loc(column)
    for r in rows:
        out.iat[int(r), col] = f"{out.iat[int(r), col]}{p.suffix}"
    primary = ["type_change"] if p.fraction > 0.05 else ["invalid_values"]
    return out, _truth(
        "schema_type_change",
        p,
        "column",
        [column],
        rows.size,
        primary,
        ["type_change", "invalid_values", "range_violation", "distribution_shift", "numeric_outlier"],
        _examples(ctx.table.raw, out, rows, column),
    )


def inject_column_removal(ctx: FaultContext, p: ColumnRemovalParams):
    column = p.column = _pick_column(ctx, p, "any")
    out = ctx.table.raw.drop(columns=[column])
    return out, _truth(
        "column_removal",
        p,
        "column",
        [column],
        len(out),
        ["column_removed"],
        [],
        [{"note": f"column '{column}' dropped"}],
    )


def inject_categories(ctx: FaultContext, p: CategoryParams):
    column = p.column = _pick_column(ctx, p, "categorical")
    existing = set(ctx.table.raw[column].dropna().astype(str))
    clashes = [v for v in p.values if v in existing]
    if clashes:
        raise FaultError(f"Values already present in '{column}': {', '.join(clashes)}")
    out = ctx.table.raw.copy()
    rows = _choose_rows(ctx, np.arange(len(out)), p.fraction, minimum=5)
    col = out.columns.get_loc(column)
    for r in rows:
        out.iat[int(r), col] = p.values[int(ctx.rng.integers(0, len(p.values)))]
    return out, _truth(
        "unexpected_categories",
        p,
        "column",
        [column],
        rows.size,
        ["new_category"],
        ["category_frequency_shift", "category_missing", "null_rate_decrease"],
        _examples(ctx.table.raw, out, rows, column),
    )


def inject_row_reduction(ctx: FaultContext, p: RowReductionParams):
    base = ctx.table.raw
    removed = _choose_rows(ctx, np.arange(len(base)), p.fraction)
    keep = np.setdiff1d(np.arange(len(base)), removed)
    out = base.iloc[keep].reset_index(drop=True)
    return out, _truth(
        "row_count_reduction",
        p,
        "dataset",
        [],
        removed.size,
        ["row_count_change"],
        [],
        [{"note": f"{removed.size} of {len(base)} rows removed"}],
    )


_GARBAGE = ["not-a-date", "0000-00-00", "31/31/2026", "N.A.", "2026-13-45"]


def inject_timestamps(ctx: FaultContext, p: TimestampParams):
    column = p.column = _pick_column(ctx, p, "datetime")
    out = ctx.table.raw.copy()
    rows = _choose_rows(ctx, np.flatnonzero(out[column].notna().to_numpy()), p.fraction, minimum=5)
    col = out.columns.get_loc(column)
    modes = {
        "mixed": ["unparseable", "epoch", "future"],
        "unparseable": ["unparseable"],
        "epoch": ["epoch"],
        "future": ["future"],
    }[p.mode]
    used = set()
    for i, r in enumerate(rows):
        mode = modes[i % len(modes)]
        used.add(mode)
        if mode == "unparseable":
            out.iat[int(r), col] = _GARBAGE[int(ctx.rng.integers(0, len(_GARBAGE)))]
        elif mode == "epoch":
            out.iat[int(r), col] = "1970-01-01T00:00:00Z"
        else:
            out.iat[int(r), col] = "2099-12-31T23:59:59Z"
    primary = sorted({"timestamp_invalid" if m == "unparseable" else "timestamp_out_of_range" for m in used})
    return out, _truth(
        "timestamp_corruption",
        p,
        "column",
        [column],
        rows.size,
        primary,
        ["timestamp_invalid", "timestamp_out_of_range", "type_change", "invalid_values", "relationship_violation"],
        _examples(ctx.table.raw, out, rows, column),
    )


def inject_referential(ctx: FaultContext, p: ReferentialParams):
    column = p.column = _pick_column(ctx, p, "key")
    out = ctx.table.raw.copy()
    rows = _choose_rows(ctx, np.flatnonzero(out[column].notna().to_numpy()), p.fraction, minimum=3)
    col = out.columns.get_loc(column)
    numeric = ctx.table.inference(column).inferred_type == "integer"
    top = int(pd.to_numeric(ctx.table.raw[column], errors="coerce").max()) if numeric else 0
    for i, r in enumerate(rows):
        out.iat[int(r), col] = str(top + 900_000 + i) if numeric else f"ORPHAN-{i:05d}"
    return out, _truth(
        "referential_integrity",
        p,
        "column",
        [column],
        rows.size,
        ["referential_integrity"],
        ["new_category", "uniqueness_lost"],
        _examples(ctx.table.raw, out, rows, column),
    )


def inject_shift(ctx: FaultContext, p: ShiftParams):
    if p.shift_std == 0 and p.scale == 1:
        raise FaultError("Set shift_std != 0 or scale != 1 to shift the distribution.")
    column = p.column = _pick_column(ctx, p, "numeric")
    out = ctx.table.raw.copy()
    typed = ctx.table.typed[column].astype("float64")
    mean, std = float(typed.mean()), float(typed.std(ddof=1))
    integer = ctx.table.inference(column).inferred_type == "integer"
    shifted = (typed - mean) * p.scale + mean + p.shift_std * std
    rows = np.flatnonzero(typed.notna().to_numpy())
    col = out.columns.get_loc(column)
    for r in rows:
        out.iat[int(r), col] = _fmt_number(shifted.iat[int(r)], integer)
    return out, _truth(
        "distribution_shift",
        p,
        "column",
        [column],
        rows.size,
        ["distribution_shift"],
        ["numeric_outlier", "range_violation", "invalid_values"],
        _examples(ctx.table.raw, out, rows, column),
        baseline_mean=mean,
        baseline_std=std,
    )


FAULT_TYPES: dict[str, FaultType] = {
    f.key: f
    for f in [
        FaultType(
            "missing_values",
            "Missing-value injection",
            "Blank out a share of a column's values.",
            MissingValuesParams,
            "any",
            ["null_rate_increase"],
            [],
            inject_missing,
        ),
        FaultType(
            "duplicate_records",
            "Duplicate records",
            "Insert exact copies of randomly chosen rows.",
            DuplicateParams,
            None,
            ["duplicate_rows"],
            [],
            inject_duplicates,
        ),
        FaultType(
            "numeric_outliers",
            "Numeric outliers",
            "Multiply a share of a numeric column by a large factor.",
            OutlierParams,
            "numeric",
            ["numeric_outlier"],
            [],
            inject_outliers,
        ),
        FaultType(
            "schema_type_change",
            "Schema type change",
            "Append a unit suffix to numeric values so the column becomes text.",
            TypeChangeParams,
            "numeric",
            ["type_change"],
            [],
            inject_type_change,
        ),
        FaultType(
            "column_removal",
            "Column removal",
            "Drop a column from the dataset.",
            ColumnRemovalParams,
            "any",
            ["column_removed"],
            [],
            inject_column_removal,
        ),
        FaultType(
            "unexpected_categories",
            "Unexpected categories",
            "Replace a share of a categorical column with unseen values.",
            CategoryParams,
            "categorical",
            ["new_category"],
            [],
            inject_categories,
        ),
        FaultType(
            "row_count_reduction",
            "Row-count reduction",
            "Randomly remove a share of the rows.",
            RowReductionParams,
            None,
            ["row_count_change"],
            [],
            inject_row_reduction,
        ),
        FaultType(
            "timestamp_corruption",
            "Timestamp corruption",
            "Replace timestamps with unparseable strings, 1970 epoch defaults or far-future dates.",
            TimestampParams,
            "datetime",
            ["timestamp_invalid", "timestamp_out_of_range"],
            [],
            inject_timestamps,
        ),
        FaultType(
            "referential_integrity",
            "Referential integrity violation",
            "Replace foreign-key values with ids that do not exist in the referenced dataset.",
            ReferentialParams,
            "key",
            ["referential_integrity"],
            [],
            inject_referential,
            note="Needs a foreign_key rule on the column: referential integrity can only be checked against "
            "a declared reference dataset.",
        ),
        FaultType(
            "distribution_shift",
            "Distribution shift",
            "Shift (and optionally rescale) every value of a numeric column.",
            ShiftParams,
            "numeric",
            ["distribution_shift"],
            [],
            inject_shift,
        ),
    ]
}


def inject(fault_type: str, ctx: FaultContext, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if fault_type not in FAULT_TYPES:
        raise FaultError(f"Unknown fault type '{fault_type}'.")
    fault = FAULT_TYPES[fault_type]
    parsed = fault.params_model.model_validate(params)
    return fault.injector(ctx, parsed)


def catalogue(ctx: FaultContext | None = None) -> list[dict[str, Any]]:
    items = []
    for fault in FAULT_TYPES.values():
        item = {
            "fault_type": fault.key,
            "label": fault.label,
            "description": fault.description,
            "column_kind": fault.column_kind,
            "expected_signals": fault.primary,
            "note": fault.note,
            "params_schema": fault.params_model.model_json_schema(),
        }
        if ctx is not None and fault.column_kind:
            item["eligible_columns"] = eligible_columns(ctx, fault.column_kind)
        items.append(item)
    return items
