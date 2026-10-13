"""Pydantic response and request models shared by the API routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True
    invalid_count: int = 0
    datetime_format: str | None = None
    mixed: bool = False


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    version_number: int
    origin: str
    original_filename: str
    file_format: str
    size_bytes: int
    sha256: str
    row_count: int
    column_count: int
    rejected_row_count: int
    duplicate_row_count: int
    status: str
    status_reason: str
    imported_at: datetime
    parent_version_id: str | None
    schema_: list[ColumnSchema] = Field(validation_alias="schema_json", serialization_alias="schema")


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str
    kind: str
    created_at: datetime
    updated_at: datetime
    version_count: int
    current_version: VersionOut | None
    asset_id: str | None


class ImportResponse(BaseModel):
    dataset: DatasetOut
    version: VersionOut
    summary: dict[str, Any]


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class QuarantineRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class PreviewOut(BaseModel):
    dataset_id: str
    version_id: str
    columns: list[ColumnSchema]
    rows: list[list[str | None]]
    row_numbers: list[int]
    total: int
    offset: int
    limit: int


class ProfileOut(BaseModel):
    dataset_id: str
    version_id: str
    version_number: int
    computed_at: datetime
    duration_ms: float
    cached: bool
    profile: dict[str, Any]


class RejectedRowsOut(BaseModel):
    version_id: str
    total: int
    truncated: bool
    rows: list[dict[str, Any]]
