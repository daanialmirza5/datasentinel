"""Typed parameters for every rule type, validated on create/update."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DataType = Literal["integer", "float", "boolean", "datetime", "string"]


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColumnExistsParams(_Params):
    pass


class NotNullParams(_Params):
    max_null_pct: float = Field(default=0.0, ge=0, le=100,
                                description="Largest acceptable percentage of missing values.")


class RangeParams(_Params):
    min: float | None = None
    max: float | None = None
    inclusive: bool = True

    @model_validator(mode="after")
    def _bounds(self) -> RangeParams:
        if self.min is None and self.max is None:
            raise ValueError("Provide at least one of min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class ExpectedTypeParams(_Params):
    type: DataType
    allow_integer_as_float: bool = True


class PatternParams(_Params):
    regex: str = Field(min_length=1, max_length=500)
    full_match: bool = True


class UniqueParams(_Params):
    extra_columns: list[str] = Field(default_factory=list, max_length=10,
                                     description="Additional columns forming a composite key.")
    ignore_nulls: bool = True


class AllowedValuesParams(_Params):
    values: list[str] = Field(min_length=1, max_length=1000)
    case_sensitive: bool = True


class AggregateRangeParams(_Params):
    aggregate: Literal["mean", "median", "sum", "min", "max", "std", "null_pct", "distinct_count"]
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _bounds(self) -> AggregateRangeParams:
        if self.min is None and self.max is None:
            raise ValueError("Provide at least one of min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class TimestampRangeParams(_Params):
    min: datetime | None = None
    max: datetime | None = None
    max_future_days: float | None = Field(default=None, ge=0,
                                          description="Reject values later than now + this many days.")

    @model_validator(mode="after")
    def _bounds(self) -> TimestampRangeParams:
        if self.min is None and self.max is None and self.max_future_days is None:
            raise ValueError("Provide min, max or max_future_days")
        return self


class RowCountParams(_Params):
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> RowCountParams:
        if self.min is None and self.max is None:
            raise ValueError("Provide at least one of min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class ColumnComparisonParams(_Params):
    operator: Literal["lt", "le", "gt", "ge", "eq", "ne"]
    other_column: str = Field(min_length=1, max_length=128)


class ForeignKeyParams(_Params):
    reference_dataset_id: str = Field(min_length=1, max_length=40)
    reference_column: str = Field(min_length=1, max_length=128)


PARAM_MODELS: dict[str, type[_Params]] = {
    "column_exists": ColumnExistsParams,
    "not_null": NotNullParams,
    "range": RangeParams,
    "expected_type": ExpectedTypeParams,
    "pattern": PatternParams,
    "unique": UniqueParams,
    "allowed_values": AllowedValuesParams,
    "aggregate_range": AggregateRangeParams,
    "timestamp_range": TimestampRangeParams,
    "row_count": RowCountParams,
    "column_comparison": ColumnComparisonParams,
    "foreign_key": ForeignKeyParams,
}
