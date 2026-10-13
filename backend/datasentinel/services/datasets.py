"""Dataset and version lifecycle: import, lookup, loading and deletion."""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.errors import ConflictError, NotFoundError, PayloadTooLarge, ValidationFailed
from datasentinel.ingestion.inference import ColumnInference, infer_frame
from datasentinel.ingestion.parser import ParsedTable, ParseLimits, detect_format, parse_bytes
from datasentinel.models import Dataset, DatasetVersion, LineageAsset, new_id
from datasentinel.storage import Storage

DATASET_NAME_RE = re.compile(r"^[\w][\w .\-()\[\]#·:]{0,119}$", re.UNICODE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class LoadedTable:
    """A parsed dataset version. Frames are shared via the cache and must not be mutated."""

    raw: pd.DataFrame
    typed: pd.DataFrame
    inferences: list[ColumnInference]
    parsed: ParsedTable

    @property
    def schema(self) -> list[dict[str, Any]]:
        return [inference.as_schema() for inference in self.inferences]

    def inference(self, column: str) -> ColumnInference | None:
        return next((inf for inf in self.inferences if inf.name == column), None)


class _TableCache:
    def __init__(self, max_items: int = 6) -> None:
        self._items: OrderedDict[str, LoadedTable] = OrderedDict()
        self._lock = threading.Lock()
        self.max_items = max_items

    def get(self, key: str) -> LoadedTable | None:
        with self._lock:
            table = self._items.get(key)
            if table is not None:
                self._items.move_to_end(key)
            return table

    def put(self, key: str, table: LoadedTable) -> None:
        with self._lock:
            self._items[key] = table
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def discard(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)


table_cache = _TableCache()


def sanitize_filename(filename: str | None) -> str:
    """Keep a display-only basename. It never becomes part of a filesystem path."""
    if not filename:
        return "upload"
    base = PurePath(filename.replace("\\", "/")).name
    base = _CONTROL.sub("", base).strip()
    return base[:255] or "upload"


def validate_dataset_name(name: str) -> str:
    cleaned = _CONTROL.sub("", name).strip()
    if not DATASET_NAME_RE.fullmatch(cleaned):
        raise ValidationFailed(
            "Dataset names must be 1-120 characters of letters, digits, spaces and . - _ ( ) [ ] # : "
            "and must start with a letter, digit or underscore.",
            details={"name": name},
        )
    return cleaned


def name_from_filename(filename: str) -> str:
    stem = PurePath(filename).stem or "dataset"
    candidate = re.sub(r"[^\w .\-()]", "_", stem)[:120].strip(" .") or "dataset"
    if not re.match(r"^\w", candidate):
        candidate = f"dataset_{candidate}"[:120]
    return candidate


def parse_limits(settings: Settings) -> ParseLimits:
    return ParseLimits(settings.max_rows, settings.max_columns, settings.max_cell_chars)


def build_table(parsed: ParsedTable) -> LoadedTable:
    typed, inferences = infer_frame(parsed.frame)
    return LoadedTable(parsed.frame, typed, inferences, parsed)


def storage_for(settings: Settings) -> Storage:
    return Storage(settings.storage_dir)


def load_table(settings: Settings, version: DatasetVersion) -> LoadedTable:
    cached = table_cache.get(version.storage_key)
    if cached is not None:
        return cached
    content = storage_for(settings).read(version.storage_key)
    # Limits were enforced at import time; re-reading an accepted file must not fail if they changed.
    limits = ParseLimits(max_rows=max(settings.max_rows, version.row_count + 1),
                         max_columns=max(settings.max_columns, version.column_count),
                         max_cell_chars=10_000_000)
    table = build_table(parse_bytes(content, version.file_format, limits))
    table_cache.put(version.storage_key, table)
    return table


def get_dataset(session: Session, dataset_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset '{dataset_id}' not found")
    return dataset


def get_version(session: Session, dataset: Dataset, version_id: str) -> DatasetVersion:
    version = session.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset.id:
        raise NotFoundError(f"Version '{version_id}' not found for dataset '{dataset.id}'")
    return version


def list_versions(session: Session, dataset_id: str) -> list[DatasetVersion]:
    return list(session.scalars(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version_number)))


def current_version(session: Session, dataset: Dataset) -> DatasetVersion | None:
    """The newest non-quarantined version (quarantining the newest one 'restores' the previous)."""
    versions = list_versions(session, dataset.id)
    active = [v for v in versions if v.status == "active"]
    if active:
        return active[-1]
    return versions[-1] if versions else None


def previous_version(session: Session, version: DatasetVersion) -> DatasetVersion | None:
    """The newest active version older than ``version``."""
    return session.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == version.dataset_id,
               DatasetVersion.version_number < version.version_number,
               DatasetVersion.status == "active")
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    ).first()


def resolve_version(session: Session, dataset: Dataset, version_id: str | None) -> DatasetVersion:
    if version_id:
        return get_version(session, dataset, version_id)
    version = current_version(session, dataset)
    if version is None:
        raise NotFoundError(f"Dataset '{dataset.id}' has no versions")
    return version


def build_import_summary(table: LoadedTable, duplicates: int) -> dict[str, Any]:
    parsed = table.parsed
    type_counts: dict[str, int] = {}
    for inference in table.inferences:
        type_counts[inference.inferred_type] = type_counts.get(inference.inferred_type, 0) + 1
    warnings = list(parsed.warnings)
    for inference in table.inferences:
        warnings.extend(f"{inference.name}: {note}" for note in inference.notes)
    return {
        "file_format": parsed.file_format,
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        "rows_accepted": len(table.raw),
        "rows_rejected": parsed.rejected_count,
        "blank_lines_skipped": parsed.blank_lines_skipped,
        "duplicate_rows": duplicates,
        "columns": int(table.raw.shape[1]),
        "type_counts": type_counts,
        "missing_cells": int(table.raw.isna().sum().sum()),
        "invalid_cells": int(sum(inf.invalid_count for inf in table.inferences)),
        "column_renames": parsed.column_renames,
        "warnings": warnings,
        "rejected_rows": [row.as_dict() for row in parsed.rejected],
        "rejected_rows_truncated": parsed.rejected_count > len(parsed.rejected),
    }


def count_duplicate_rows(frame: pd.DataFrame) -> int:
    if frame.empty or frame.shape[1] == 0:
        return 0
    return int(frame.duplicated(keep="first").sum())


def ensure_dataset_asset(session: Session, dataset: Dataset) -> LineageAsset:
    """Every dataset is a lineage node so impact can be traced through it."""
    asset = session.scalar(select(LineageAsset).where(LineageAsset.dataset_id == dataset.id))
    if asset is not None:
        return asset
    name = dataset.name
    if session.scalar(select(LineageAsset).where(LineageAsset.name == name)) is not None:
        name = f"{dataset.name} (dataset)"[:120]
    asset = LineageAsset(name=name, kind="dataset", dataset_id=dataset.id,
                         description=dataset.description)
    session.add(asset)
    session.flush()
    return asset


def import_version(
    session: Session,
    settings: Settings,
    *,
    content: bytes,
    filename: str | None,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    description: str = "",
    file_format: str | None = None,
    origin: str = "upload",
    kind: str = "user",
    parent_version_id: str | None = None,
    run_analysis: bool = True,
) -> DatasetVersion:
    """Parse, store and register a new dataset version. Never overwrites an existing version."""
    display_name = sanitize_filename(filename)
    fmt = detect_format(display_name, file_format)
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLarge(f"File exceeds the {settings.max_upload_mb:g} MB upload limit")

    if dataset_id:
        dataset = get_dataset(session, dataset_id)
        version_count = session.scalar(
            select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)) or 0
        if version_count >= settings.max_versions_per_dataset:
            raise ConflictError(
                f"Dataset already has {version_count} versions (limit {settings.max_versions_per_dataset}). "
                "Delete old versions or raise DATASENTINEL_MAX_VERSIONS_PER_DATASET.")
    else:
        name = validate_dataset_name(dataset_name or name_from_filename(display_name))
        if session.scalar(select(Dataset).where(Dataset.name == name)) is not None:
            raise ConflictError(
                f"A dataset named '{name}' already exists. Import into it as a new version instead, "
                "or choose another name.", details={"name": name})
        dataset = Dataset(name=name, description=description.strip()[:2000], kind=kind)
        session.add(dataset)
        session.flush()
        ensure_dataset_asset(session, dataset)

    parsed = parse_bytes(content, fmt, parse_limits(settings))
    table = build_table(parsed)
    duplicates = count_duplicate_rows(table.raw)
    next_number = (session.scalar(
        select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset.id)) or 0) + 1

    version_id = new_id("ver")
    storage_key = f"{version_id}.{fmt}"
    storage = storage_for(settings)
    storage.write(storage_key, content)
    try:
        version = DatasetVersion(
            id=version_id,
            dataset_id=dataset.id,
            version_number=next_number,
            origin=origin,
            original_filename=display_name,
            storage_key=storage_key,
            file_format=fmt,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            row_count=len(table.raw),
            column_count=int(table.raw.shape[1]),
            rejected_row_count=parsed.rejected_count,
            duplicate_row_count=duplicates,
            schema_json=table.schema,
            import_summary=build_import_summary(table, duplicates),
            parent_version_id=parent_version_id,
        )
        session.add(version)
        session.flush()
        table_cache.put(storage_key, table)
        identical = session.scalar(
            select(DatasetVersion.version_number).where(
                DatasetVersion.dataset_id == dataset.id, DatasetVersion.sha256 == version.sha256,
                DatasetVersion.id != version.id))
        if identical is not None:
            version.import_summary = {**version.import_summary, "warnings": [
                *version.import_summary["warnings"],
                f"Content is byte-identical to version {identical}."]}
        if run_analysis:
            from datasentinel.services.monitoring import analyze_new_version
            analyze_new_version(session, settings, version)
        dataset.updated_at = version.imported_at
        session.flush()
    except BaseException:
        storage.delete(storage_key)
        table_cache.discard(storage_key)
        raise
    return version


def delete_dataset(session: Session, settings: Settings, dataset: Dataset) -> int:
    """Delete a dataset, its versions' files and generated lab datasets. Returns files removed."""
    from datasentinel.models import Experiment

    storage = storage_for(settings)
    lab_ids = [exp.lab_dataset_id for exp in session.scalars(
        select(Experiment).where(Experiment.dataset_id == dataset.id)) if exp.lab_dataset_id]
    targets = [dataset, *[d for d in (session.get(Dataset, i) for i in lab_ids) if d is not None]]
    removed = 0
    keys: list[str] = []
    for target in targets:
        keys.extend(v.storage_key for v in list_versions(session, target.id))
    for target in targets[1:]:
        session.delete(target)
    session.delete(dataset)
    session.flush()
    for key in keys:
        storage.delete(key)
        table_cache.discard(key)
        removed += 1
    return removed


def delete_version(session: Session, settings: Settings, version: DatasetVersion) -> None:
    key = version.storage_key
    session.delete(version)
    session.flush()
    storage_for(settings).delete(key)
    table_cache.discard(key)
