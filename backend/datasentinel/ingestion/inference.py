"""Column type inference over string cells.

A column is assigned the most specific type that at least ``CONFORMANCE_THRESHOLD`` (95%) of its
non-missing values conform to, checked in the order boolean → integer → float → datetime. The
non-conforming remainder is reported as *invalid values* rather than silently coerced. Columns
below the threshold for every type are strings; if most (but not 95%) of their values look
numeric they are flagged as ``mixed`` so the profile can explain the ambiguity.

Deliberate choices:

* "0"/"1" are integers, not booleans; only word tokens (true/false/yes/no/t/f/y/n) are booleans.
* Numbers with leading zeros ("00123") are kept as strings: they are almost always identifiers
  or codes, and converting them would destroy information.
* Datetimes must look like dates (ISO 8601 or day/month/year with separators). Bare integers are
  never interpreted as epoch timestamps.
* When a slash-separated date format is ambiguous (every day value is <= 12) month-first is used
  and a warning is recorded.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

CONFORMANCE_THRESHOLD = 0.95
MIXED_THRESHOLD = 0.5
TYPES = ("empty", "boolean", "integer", "float", "datetime", "string")

BOOL_TRUE = frozenset({"true", "yes", "t", "y"})
BOOL_FALSE = frozenset({"false", "no", "f", "n"})
_INT_RE = r"[+-]?\d{1,18}"
_FLOAT_RE = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_LEADING_ZERO_RE = r"[+-]?0\d+"
_DATE_PREFILTER = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{4}/\d{1,2}/\d{1,2})")
_ALT_DATE_FORMATS = (
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
)


@dataclass
class ColumnInference:
    name: str
    inferred_type: str
    non_null_count: int
    invalid_count: int = 0
    invalid_examples: list[str] = field(default_factory=list)
    datetime_format: str | None = None
    mixed: bool = False
    numeric_like_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.inferred_type,
            "nullable": True,
            "invalid_count": self.invalid_count,
            "datetime_format": self.datetime_format,
            "mixed": self.mixed,
        }


def _fullmatch(values: pd.Series, pattern: str) -> pd.Series:
    return values.str.fullmatch(pattern, na=False)


def parse_datetimes(values: pd.Series, fmt: str | None) -> pd.Series:
    """Parse strings to UTC timestamps; unparseable values become NaT."""
    candidates = values.where(values.astype("string").str.match(_DATE_PREFILTER.pattern, na=False))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if fmt in (None, "ISO8601"):
            return pd.to_datetime(candidates, format="ISO8601", errors="coerce", utc=True)
        return pd.to_datetime(candidates, format=fmt, errors="coerce", utc=True)


def _best_datetime_format(values: pd.Series) -> tuple[str | None, float, bool]:
    """Return (format, conformance fraction, ambiguous)."""
    if values.empty:
        return None, 0.0, False
    looks_like_date = values.str.match(_DATE_PREFILTER.pattern, na=False)
    if looks_like_date.mean() < CONFORMANCE_THRESHOLD:
        return None, float(looks_like_date.mean()), False
    sample = values if len(values) <= 5000 else values.sample(5000, random_state=0)
    scores: dict[str, float] = {"ISO8601": float(parse_datetimes(sample, "ISO8601").notna().mean())}
    if scores["ISO8601"] < CONFORMANCE_THRESHOLD:
        for fmt in _ALT_DATE_FORMATS:
            scores[fmt] = float(parse_datetimes(sample, fmt).notna().mean())
    best = max(scores, key=lambda key: scores[key])
    ambiguous = (best == "%m/%d/%Y" and scores.get("%d/%m/%Y", 0.0) >= CONFORMANCE_THRESHOLD) or (
        best == "%m/%d/%Y %H:%M" and scores.get("%d/%m/%Y %H:%M", 0.0) >= CONFORMANCE_THRESHOLD
    )
    return best, scores[best], ambiguous


def infer_column(name: str, column: pd.Series) -> ColumnInference:
    non_null = column.dropna().astype(str)
    count = int(non_null.size)
    if count == 0:
        return ColumnInference(name, "empty", 0, notes=["Column contains only missing values."])

    lowered = non_null.str.lower()
    is_bool = lowered.isin(BOOL_TRUE | BOOL_FALSE)
    is_int = _fullmatch(non_null, _INT_RE)
    is_num = _fullmatch(non_null, _FLOAT_RE)
    has_leading_zero = bool(_fullmatch(non_null, _LEADING_ZERO_RE).any())

    def build(type_name: str, conforming: pd.Series, **extra: Any) -> ColumnInference:
        invalid = non_null[~conforming]
        examples = [str(v)[:80] for v in pd.unique(invalid)[:5]]
        return ColumnInference(name, type_name, count, int(invalid.size), examples, **extra)

    if is_bool.mean() >= CONFORMANCE_THRESHOLD:
        return build("boolean", is_bool)
    if not has_leading_zero:
        if is_int.mean() >= CONFORMANCE_THRESHOLD:
            return build("integer", is_int)
        if is_num.mean() >= CONFORMANCE_THRESHOLD:
            return build("float", is_num)

    fmt, dt_score, ambiguous = _best_datetime_format(non_null)
    if fmt is not None and dt_score >= CONFORMANCE_THRESHOLD:
        parsed = parse_datetimes(non_null, fmt)
        result = build("datetime", parsed.notna(), datetime_format=fmt)
        if ambiguous:
            result.notes.append("Date format is ambiguous (day and month both <= 12); assumed month-first.")
        return result

    result = ColumnInference(name, "string", count)
    numeric_pct = float(is_num.mean())
    if has_leading_zero and is_int.mean() >= CONFORMANCE_THRESHOLD:
        result.notes.append("Digits with leading zeros are treated as identifiers/codes, not numbers.")
    elif MIXED_THRESHOLD <= numeric_pct < CONFORMANCE_THRESHOLD:
        result.mixed = True
        result.numeric_like_pct = round(numeric_pct * 100, 2)
        result.notes.append(f"{result.numeric_like_pct}% of values look numeric; column treated as text.")
    return result


def to_typed(column: pd.Series, inference: ColumnInference) -> pd.Series:
    """Convert a string column to its inferred type; invalid values become missing."""
    kind = inference.inferred_type
    if kind == "integer":
        text = column.astype("string")
        valid = text.str.fullmatch(_INT_RE, na=False).to_numpy(dtype=bool)
        out = pd.Series(pd.NA, index=column.index, dtype="Int64")
        if valid.any():
            out[valid] = text[valid].astype("int64").to_numpy()
        return out
    if kind == "float":
        text = column.astype("string")
        valid = text.str.fullmatch(_FLOAT_RE, na=False)
        return pd.to_numeric(text.where(valid), errors="coerce").astype("float64")
    if kind == "boolean":
        lowered = column.astype("string").str.lower()
        mapped = pd.Series(pd.NA, index=column.index, dtype="boolean")
        mapped[lowered.isin(BOOL_TRUE).fillna(False).astype(bool)] = True
        mapped[lowered.isin(BOOL_FALSE).fillna(False).astype(bool)] = False
        return mapped
    if kind == "datetime":
        return parse_datetimes(column, inference.datetime_format)
    if kind == "empty":
        return pd.Series(np.nan, index=column.index, dtype="float64")
    return column.astype(object)


def infer_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[ColumnInference]]:
    inferences = [infer_column(str(name), frame[name]) for name in frame.columns]
    typed = pd.DataFrame({inf.name: to_typed(frame[inf.name], inf) for inf in inferences}, index=frame.index)
    return typed, inferences
