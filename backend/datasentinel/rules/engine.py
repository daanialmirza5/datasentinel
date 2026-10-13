"""Data quality rule evaluation.

Every evaluation returns one of four statuses — never a silent pass:

* ``passed``         the rule was evaluated over at least one value and no violation was found;
* ``failed``         at least one violation (or the dataset-level condition does not hold);
* ``not_evaluated``  the rule could not be applied (column absent, no non-null values, reference
                     dataset unavailable, incompatible types). The reason is in ``message``;
* ``error``          evaluation was attempted but aborted (invalid regex, regex timeout).

Row-level rules ignore missing values (``not_null`` is the rule for those) and count each
offending row once. Examples contain only the columns the rule inspects, with 1-based row numbers
of the parsed data.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import regex

from datasentinel.ingestion.inference import (
    _FLOAT_RE,
    _INT_RE,
    BOOL_FALSE,
    BOOL_TRUE,
    parse_datetimes,
)
from datasentinel.rules import params as P
from datasentinel.services.datasets import LoadedTable

SEVERITIES = ("low", "medium", "high", "critical")

RULE_TYPES: dict[str, dict[str, Any]] = {
    "column_exists": {
        "label": "Column must exist",
        "requires_column": True,
        "scope": "schema",
        "signal_category": "column_removed",
        "description": "Fails when the column is missing from the version.",
        "recommendation": "Inspect the most recent source schema change: '{column}' was expected but is absent. "
        "Check whether it was renamed or dropped upstream before downstream jobs read it.",
    },
    "not_null": {
        "label": "No missing values",
        "requires_column": True,
        "scope": "row",
        "signal_category": "null_rate_increase",
        "description": "Share of missing values must not exceed max_null_pct (default 0%).",
        "recommendation": "Investigate why '{column}' has missing values: check the extraction query, joins that "
        "may not match, and optional fields in the source system.",
    },
    "range": {
        "label": "Numeric range",
        "requires_column": True,
        "scope": "row",
        "signal_category": "range_violation",
        "description": "Every non-missing value must be numeric and within [min, max].",
        "recommendation": "Validate the expected range of '{column}': inspect the offending rows for unit or "
        "scaling errors (e.g. cents vs. units) and for non-numeric values.",
    },
    "expected_type": {
        "label": "Expected type",
        "requires_column": True,
        "scope": "schema",
        "signal_category": "type_change",
        "description": "The column must have the expected data type and every value must conform to it.",
        "recommendation": "Compare the type of '{column}' with the previous version and the producer's schema; "
        "a type change often means a formatting change upstream (units, locales, quoting).",
    },
    "pattern": {
        "label": "Matches pattern",
        "requires_column": True,
        "scope": "row",
        "signal_category": "pattern_violation",
        "description": "Every non-missing value must match a regular expression.",
        "recommendation": "Review values of '{column}' that do not match the expected format and fix the "
        "producer or add an explicit normalisation step.",
    },
    "unique": {
        "label": "Unique values",
        "requires_column": True,
        "scope": "row",
        "signal_category": "uniqueness_lost",
        "description": "Values (optionally a composite key) must not repeat.",
        "recommendation": "Look for duplicated records in '{column}': replayed batches, retried loads or "
        "fan-out joins are common causes. De-duplicate before downstream aggregation.",
    },
    "allowed_values": {
        "label": "Allowed values",
        "requires_column": True,
        "scope": "row",
        "signal_category": "new_category",
        "description": "Every non-missing value must belong to the configured set.",
        "recommendation": "Confirm whether the new values in '{column}' are legitimate (then extend the "
        "allowed set) or a mapping/encoding defect upstream.",
    },
    "aggregate_range": {
        "label": "Aggregate within limits",
        "requires_column": True,
        "scope": "dataset",
        "signal_category": "distribution_shift",
        "description": "A column aggregate (mean, median, sum, min, max, std, null_pct, distinct_count) must "
        "stay within limits.",
        "recommendation": "The aggregate of '{column}' moved outside its configured limits; compare the "
        "distribution with the previous version before trusting downstream metrics.",
    },
    "timestamp_range": {
        "label": "Timestamp window",
        "requires_column": True,
        "scope": "row",
        "signal_category": "timestamp_invalid",
        "description": "Timestamps must parse and fall within [min, max] and/or not lie too far in the future.",
        "recommendation": "Check '{column}' for unparseable, default (1970) or future-dated timestamps; verify "
        "time-zone handling and date formats in the producer.",
    },
    "row_count": {
        "label": "Row count",
        "requires_column": False,
        "scope": "dataset",
        "signal_category": "row_count_change",
        "description": "The number of rows must be within [min, max].",
        "recommendation": "Row volume is outside the expected bounds: check for partial loads, filters "
        "applied upstream, or duplicated batches.",
    },
    "column_comparison": {
        "label": "Column relationship",
        "requires_column": True,
        "scope": "row",
        "signal_category": "relationship_violation",
        "description": "For rows where both values are present, '<column> <operator> <other_column>' must hold "
        "(numeric or datetime columns).",
        "recommendation": "Rows violate the documented relationship between '{column}' and the compared column; "
        "check transformation logic and the order of event timestamps.",
    },
    "foreign_key": {
        "label": "Referential integrity",
        "requires_column": True,
        "scope": "row",
        "signal_category": "referential_integrity",
        "description": "Every non-missing value must exist in a column of another dataset's current version.",
        "recommendation": "Values in '{column}' reference records that do not exist in the reference dataset: "
        "check load ordering between the datasets and whether reference data is stale.",
    },
}

OPERATORS: dict[str, tuple[str, Callable[[Any, Any], Any]]] = {
    "lt": ("<", lambda a, b: a < b),
    "le": ("<=", lambda a, b: a <= b),
    "gt": (">", lambda a, b: a > b),
    "ge": (">=", lambda a, b: a >= b),
    "eq": ("==", lambda a, b: a == b),
    "ne": ("!=", lambda a, b: a != b),
}


@dataclass
class RuleSpec:
    rule_type: str
    column: str | None
    params: dict[str, Any]
    name: str = ""
    severity: str = "medium"


@dataclass
class EvalContext:
    table: LoadedTable
    resolve_reference: Callable[[str], LoadedTable | None] = lambda _id: None
    example_limit: int = 5
    regex_timeout_seconds: float = 2.0
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RuleOutcome:
    status: str
    evaluated_count: int = 0
    violation_count: int = 0
    message: str = ""
    examples: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def violation_pct(self) -> float:
        return round(100.0 * self.violation_count / self.evaluated_count, 4) if self.evaluated_count else 0.0


def recommendation_for(spec: RuleSpec) -> str:
    template = RULE_TYPES.get(spec.rule_type, {}).get("recommendation", "Investigate the failing rule.")
    return template.format(column=spec.column or "")


def _not_evaluated(reason: str, **details: Any) -> RuleOutcome:
    return RuleOutcome("not_evaluated", message=reason, details=details)


def _examples(table: LoadedTable, mask: np.ndarray | pd.Series, columns: list[str], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    positions = np.flatnonzero(np.asarray(mask, dtype=bool))[:limit]
    rows = table.raw.iloc[positions]
    return [{"row": int(index) + 1, "values": {c: rows.at[index, c] for c in columns}} for index in rows.index]


def _row_outcome(
    table: LoadedTable,
    evaluated: pd.Series,
    violations: pd.Series,
    columns: list[str],
    ctx: EvalContext,
    describe: str,
    **details: Any,
) -> RuleOutcome:
    evaluated_count = int(evaluated.sum())
    if evaluated_count == 0:
        return _not_evaluated("No non-missing values to evaluate.")
    violation_mask = (violations & evaluated).to_numpy(dtype=bool)
    count = int(violation_mask.sum())
    outcome = RuleOutcome("failed" if count else "passed", evaluated_count, count, details=details)
    outcome.message = (
        f"{count} of {evaluated_count} values {describe}."
        if count
        else f"All {evaluated_count} values satisfy the rule."
    )
    outcome.examples = _examples(table, violation_mask, columns, ctx.example_limit)
    return outcome


def _numeric(table: LoadedTable, column: str) -> pd.Series:
    """Numeric view of a column whatever its inferred type (non-numeric text -> NaN)."""
    typed = table.typed[column]
    if pd.api.types.is_numeric_dtype(typed) and not pd.api.types.is_bool_dtype(typed):
        return typed.astype("float64")
    raw = table.raw[column].astype("string")
    return pd.to_numeric(raw.where(raw.str.fullmatch(_FLOAT_RE, na=False)), errors="coerce").astype("float64")


def _datetimes(table: LoadedTable, column: str) -> pd.Series:
    typed = table.typed[column]
    if pd.api.types.is_datetime64_any_dtype(typed):
        return typed
    return parse_datetimes(table.raw[column].astype(object), "ISO8601")


def _conforms(raw: pd.Series, data_type: str) -> pd.Series:
    text = raw.astype("string")
    if data_type == "integer":
        return text.str.fullmatch(_INT_RE, na=False)
    if data_type == "float":
        return text.str.fullmatch(_FLOAT_RE, na=False)
    if data_type == "boolean":
        return text.str.lower().isin(BOOL_TRUE | BOOL_FALSE).fillna(False).astype(bool)
    if data_type == "datetime":
        return parse_datetimes(raw.astype(object), "ISO8601").notna()
    return pd.Series(True, index=raw.index)


# ---------------------------------------------------------------- evaluators


def _column_exists(spec: RuleSpec, ctx: EvalContext, _p: P.ColumnExistsParams) -> RuleOutcome:
    present = spec.column in ctx.table.raw.columns
    return RuleOutcome(
        "passed" if present else "failed",
        1,
        0 if present else 1,
        message=f"Column '{spec.column}' is {'present' if present else 'missing'}.",
    )


def _not_null(spec: RuleSpec, ctx: EvalContext, p: P.NotNullParams) -> RuleOutcome:
    raw = ctx.table.raw[spec.column]
    total = int(raw.size)
    if total == 0:
        return _not_evaluated("The version has no rows.")
    nulls = raw.isna()
    count = int(nulls.sum())
    pct = 100.0 * count / total
    status = "passed" if pct <= p.max_null_pct else "failed"
    outcome = RuleOutcome(status, total, count, details={"null_pct": round(pct, 4), "max_null_pct": p.max_null_pct})
    outcome.message = f"{count} of {total} rows ({pct:.2f}%) are missing '{spec.column}' (allowed: {p.max_null_pct}%)."
    if status == "failed":
        outcome.examples = _examples(ctx.table, nulls.to_numpy(), [spec.column], ctx.example_limit)
    return outcome


def _range(spec: RuleSpec, ctx: EvalContext, p: P.RangeParams) -> RuleOutcome:
    raw = ctx.table.raw[spec.column]
    numbers = _numeric(ctx.table, spec.column)
    evaluated = raw.notna()
    out_of_range = pd.Series(False, index=raw.index)
    if p.min is not None:
        out_of_range |= (numbers < p.min) if p.inclusive else (numbers <= p.min)
    if p.max is not None:
        out_of_range |= (numbers > p.max) if p.inclusive else (numbers >= p.max)
    non_numeric = evaluated & numbers.isna()
    bounds = f"[{'-inf' if p.min is None else p.min}, {'inf' if p.max is None else p.max}]"
    return _row_outcome(
        ctx.table,
        evaluated,
        out_of_range.fillna(False) | non_numeric,
        [spec.column],
        ctx,
        f"are non-numeric or outside {bounds}",
        non_numeric=int(non_numeric.sum()),
        out_of_range=int((out_of_range.fillna(False) & evaluated).sum()),
    )


def _expected_type(spec: RuleSpec, ctx: EvalContext, p: P.ExpectedTypeParams) -> RuleOutcome:
    raw = ctx.table.raw[spec.column]
    inference = ctx.table.inference(spec.column)
    actual = inference.inferred_type if inference else "unknown"
    if actual == "empty":
        return _not_evaluated("Column has no non-missing values; its type cannot be determined.")
    compatible = actual == p.type or (p.allow_integer_as_float and p.type == "float" and actual == "integer")
    evaluated = raw.notna()
    check_type = "float" if (p.type == "float" and p.allow_integer_as_float) else p.type
    violations = evaluated & ~_conforms(raw, check_type)
    outcome = _row_outcome(
        ctx.table,
        evaluated,
        violations,
        [spec.column],
        ctx,
        f"do not conform to {p.type}",
        inferred_type=actual,
        expected_type=p.type,
    )
    if not compatible:
        outcome.status = "failed"
        outcome.message = f"Column '{spec.column}' is inferred as {actual}, expected {p.type}. " + outcome.message
    return outcome


def _pattern(spec: RuleSpec, ctx: EvalContext, p: P.PatternParams) -> RuleOutcome:
    try:
        compiled = regex.compile(p.regex)
    except regex.error as exc:
        return RuleOutcome("error", message=f"Invalid regular expression: {exc}")
    raw = ctx.table.raw[spec.column]
    evaluated = raw.notna()
    deadline = time.monotonic() + ctx.regex_timeout_seconds
    matches: dict[str, bool] = {}
    matcher = compiled.fullmatch if p.full_match else compiled.search
    try:
        for value in pd.unique(raw[evaluated].astype(str)):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            matches[value] = matcher(value, timeout=remaining) is not None
    except TimeoutError:
        return RuleOutcome(
            "error",
            message=f"Pattern evaluation exceeded {ctx.regex_timeout_seconds}s and was "
            "aborted; simplify the regular expression.",
        )
    violations = raw.map(lambda v: v is not None and not matches.get(str(v), True))
    return _row_outcome(ctx.table, evaluated, violations.astype(bool), [spec.column], ctx, f"do not match /{p.regex}/")


def _unique(spec: RuleSpec, ctx: EvalContext, p: P.UniqueParams) -> RuleOutcome:
    columns = [spec.column, *p.extra_columns]
    missing = [c for c in columns if c not in ctx.table.raw.columns]
    if missing:
        return _not_evaluated(f"Key column(s) not present: {', '.join(missing)}.")
    keys = ctx.table.raw[columns]
    evaluated = keys.notna().all(axis=1) if p.ignore_nulls else pd.Series(True, index=keys.index)
    duplicated = keys[evaluated].duplicated(keep="first").reindex(keys.index, fill_value=False)
    outcome = _row_outcome(ctx.table, evaluated, duplicated, columns, ctx, "repeat an earlier key")
    outcome.details["duplicate_keys"] = int(keys[evaluated][duplicated[evaluated]].drop_duplicates().shape[0])
    return outcome


def _allowed_values(spec: RuleSpec, ctx: EvalContext, p: P.AllowedValuesParams) -> RuleOutcome:
    raw = ctx.table.raw[spec.column]
    evaluated = raw.notna()
    if p.case_sensitive:
        allowed = set(p.values)
        violations = evaluated & ~raw.isin(allowed)
    else:
        allowed = {v.lower() for v in p.values}
        violations = evaluated & ~raw.astype("string").str.lower().isin(allowed).fillna(False).astype(bool)
    unexpected = raw[violations].astype(str).value_counts().head(20)
    return _row_outcome(
        ctx.table,
        evaluated,
        violations,
        [spec.column],
        ctx,
        "are not in the allowed set",
        unexpected_values={str(k): int(v) for k, v in unexpected.items()},
    )


def _aggregate_range(spec: RuleSpec, ctx: EvalContext, p: P.AggregateRangeParams) -> RuleOutcome:
    raw = ctx.table.raw[spec.column]
    if p.aggregate == "null_pct":
        if raw.size == 0:
            return _not_evaluated("The version has no rows.")
        value: float | None = 100.0 * float(raw.isna().mean())
    elif p.aggregate == "distinct_count":
        value = float(raw.nunique())
    else:
        numbers = _numeric(ctx.table, spec.column).dropna()
        if numbers.empty:
            return _not_evaluated(f"Column '{spec.column}' has no numeric values to aggregate.")
        if p.aggregate == "std" and numbers.size < 2:
            return _not_evaluated("Standard deviation needs at least two values.")
        value = float(getattr(numbers, p.aggregate)())
    low_ok = p.min is None or value >= p.min
    high_ok = p.max is None or value <= p.max
    ok = low_ok and high_ok
    return RuleOutcome(
        "passed" if ok else "failed",
        1,
        0 if ok else 1,
        message=f"{p.aggregate}({spec.column}) = {value:.6g}; allowed "
        f"[{'-inf' if p.min is None else p.min}, {'inf' if p.max is None else p.max}].",
        details={"value": value, "aggregate": p.aggregate},
    )


def _timestamp_range(spec: RuleSpec, ctx: EvalContext, p: P.TimestampRangeParams) -> RuleOutcome:
    raw = ctx.table.raw[spec.column]
    stamps = _datetimes(ctx.table, spec.column)
    evaluated = raw.notna()
    unparseable = evaluated & stamps.isna()
    bad = unparseable.copy()

    def as_utc(moment: datetime) -> pd.Timestamp:
        ts = pd.Timestamp(moment)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    if p.min is not None:
        bad |= (stamps < as_utc(p.min)).fillna(False)
    if p.max is not None:
        bad |= (stamps > as_utc(p.max)).fillna(False)
    if p.max_future_days is not None:
        bad |= (stamps > as_utc(ctx.now + timedelta(days=p.max_future_days))).fillna(False)
    return _row_outcome(
        ctx.table,
        evaluated,
        bad.astype(bool),
        [spec.column],
        ctx,
        "are unparseable or outside the allowed window",
        unparseable=int(unparseable.sum()),
    )


def _row_count(_spec: RuleSpec, ctx: EvalContext, p: P.RowCountParams) -> RuleOutcome:
    rows = len(ctx.table.raw)
    ok = (p.min is None or rows >= p.min) and (p.max is None or rows <= p.max)
    return RuleOutcome(
        "passed" if ok else "failed",
        1,
        0 if ok else 1,
        message=f"Version has {rows} rows; allowed "
        f"[{p.min if p.min is not None else 0}, {p.max if p.max is not None else 'inf'}].",
        details={"row_count": rows},
    )


def _column_comparison(spec: RuleSpec, ctx: EvalContext, p: P.ColumnComparisonParams) -> RuleOutcome:
    if p.other_column not in ctx.table.raw.columns:
        return _not_evaluated(f"Compared column '{p.other_column}' is not present.")
    left_inf, right_inf = ctx.table.inference(spec.column), ctx.table.inference(p.other_column)
    kinds = {left_inf.inferred_type if left_inf else "", right_inf.inferred_type if right_inf else ""}
    # A text column may be compared with a typed one: its values are parsed and rows that do not
    # parse are excluded from evaluation (reported in details), never counted as passing.
    if kinds & {"integer", "float"} and kinds <= {"integer", "float", "string"}:
        left, right = _numeric(ctx.table, spec.column), _numeric(ctx.table, p.other_column)
    elif "datetime" in kinds and kinds <= {"datetime", "string"}:
        left, right = _datetimes(ctx.table, spec.column), _datetimes(ctx.table, p.other_column)
    else:
        return _not_evaluated(f"Columns must both be numeric or both datetime (found {sorted(kinds)}).")
    symbol, op = OPERATORS[p.operator]
    both_present = ctx.table.raw[spec.column].notna() & ctx.table.raw[p.other_column].notna()
    evaluated = left.notna() & right.notna()
    holds = pd.Series(op(left, right), index=left.index).fillna(False).astype(bool)
    return _row_outcome(
        ctx.table,
        evaluated,
        ~holds,
        [spec.column, p.other_column],
        ctx,
        f"violate {spec.column} {symbol} {p.other_column}",
        unparseable_rows=int((both_present & ~evaluated).sum()),
    )


def _canonical_keys(series: pd.Series) -> pd.Series:
    """Normalise integer-looking keys ('7', '7.0', '+7') so the same id compares equal across files."""
    text = series.astype("string").str.strip()
    numeric = pd.to_numeric(text.where(text.str.fullmatch(_FLOAT_RE, na=False)), errors="coerce")
    integral = numeric.notna() & (numeric % 1 == 0)
    out = text.astype(object)
    out[integral] = numeric[integral].astype("int64").astype(str)
    return out


def _foreign_key(spec: RuleSpec, ctx: EvalContext, p: P.ForeignKeyParams) -> RuleOutcome:
    reference = ctx.resolve_reference(p.reference_dataset_id)
    if reference is None:
        return _not_evaluated(
            "Reference dataset is unavailable, so referential integrity was not checked.",
            reference_dataset_id=p.reference_dataset_id,
        )
    if p.reference_column not in reference.raw.columns:
        return _not_evaluated(f"Reference column '{p.reference_column}' is not present in the reference dataset.")
    allowed = set(_canonical_keys(reference.raw[p.reference_column].dropna()))
    raw = ctx.table.raw[spec.column]
    evaluated = raw.notna()
    keys = _canonical_keys(raw)
    violations = evaluated & ~keys.isin(allowed)
    orphans = raw[violations].astype(str).value_counts().head(20)
    return _row_outcome(
        ctx.table,
        evaluated,
        violations,
        [spec.column],
        ctx,
        "have no matching record in the reference dataset",
        orphan_values={str(k): int(v) for k, v in orphans.items()},
        reference_keys=len(allowed),
    )


EVALUATORS: dict[str, Callable[[RuleSpec, EvalContext, Any], RuleOutcome]] = {
    "column_exists": _column_exists,
    "not_null": _not_null,
    "range": _range,
    "expected_type": _expected_type,
    "pattern": _pattern,
    "unique": _unique,
    "allowed_values": _allowed_values,
    "aggregate_range": _aggregate_range,
    "timestamp_range": _timestamp_range,
    "row_count": _row_count,
    "column_comparison": _column_comparison,
    "foreign_key": _foreign_key,
}


def evaluate(spec: RuleSpec, ctx: EvalContext) -> RuleOutcome:
    if spec.rule_type not in EVALUATORS:
        return RuleOutcome("error", message=f"Unknown rule type '{spec.rule_type}'.")
    try:
        params = P.PARAM_MODELS[spec.rule_type].model_validate(spec.params)
    except ValueError as exc:
        return RuleOutcome("error", message=f"Invalid rule parameters: {exc}")
    if RULE_TYPES[spec.rule_type]["requires_column"] and spec.rule_type != "column_exists":
        if not spec.column:
            return RuleOutcome("error", message="Rule requires a column.")
        if spec.column not in ctx.table.raw.columns:
            return _not_evaluated(f"Column '{spec.column}' is not present in this version.")
    return EVALUATORS[spec.rule_type](spec, ctx, params)
