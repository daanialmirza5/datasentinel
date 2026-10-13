from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from datasentinel.api.deps import get_db, get_settings_dep
from datasentinel.config import Settings
from datasentinel.errors import ConflictError, PayloadTooLarge
from datasentinel.models import Dataset, DatasetVersion, LineageAsset
from datasentinel.schemas import (
    ColumnSchema,
    DatasetOut,
    DatasetUpdate,
    ImportResponse,
    Page,
    PreviewOut,
    ProfileOut,
    QuarantineRequest,
    RejectedRowsOut,
    VersionOut,
)
from datasentinel.services import datasets as svc
from datasentinel.services.profiles import get_or_compute_profile

router = APIRouter(prefix="/datasets", tags=["datasets"])

_CHUNK = 1024 * 1024


def dataset_out(session: Session, dataset: Dataset) -> DatasetOut:
    versions = svc.list_versions(session, dataset.id)
    current = svc.current_version(session, dataset)
    asset_id = session.scalar(select(LineageAsset.id).where(LineageAsset.dataset_id == dataset.id))
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        kind=dataset.kind,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        version_count=len(versions),
        current_version=VersionOut.model_validate(current) if current else None,
        asset_id=asset_id,
    )


def _read_upload(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge(f"File exceeds the {limit} byte upload limit")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/import", response_model=ImportResponse, status_code=201)
def import_dataset(
    file: Annotated[UploadFile, File(description="CSV, TSV, JSON (array of objects) or JSON Lines file")],
    dataset_name: Annotated[str | None, Form(max_length=120)] = None,
    dataset_id: Annotated[str | None, Form(max_length=40)] = None,
    description: Annotated[str, Form(max_length=2000)] = "",
    file_format: Annotated[str | None, Form(pattern=r"^(csv|json|jsonl)$")] = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> ImportResponse:
    """Import a file as a new dataset, or as the next version of ``dataset_id``.

    The upload is parsed and validated, stored under a server-generated key, profiled, checked
    against the dataset's enabled rules and compared with the previous version.
    """
    content = _read_upload(file, settings.max_upload_bytes)
    version = svc.import_version(
        session,
        settings,
        content=content,
        filename=file.filename,
        dataset_id=dataset_id or None,
        dataset_name=dataset_name or None,
        description=description,
        file_format=file_format,
    )
    dataset = svc.get_dataset(session, version.dataset_id)
    return ImportResponse(
        dataset=dataset_out(session, dataset),
        version=VersionOut.model_validate(version),
        summary=version.import_summary,
    )


@router.get("", response_model=Page[DatasetOut])
def list_datasets(
    q: Annotated[str | None, Query(max_length=120, description="Case-insensitive name filter")] = None,
    kind: Annotated[str | None, Query(pattern=r"^(user|sample|lab)$")] = None,
    include_lab: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_db),
) -> Page[DatasetOut]:
    query = select(Dataset)
    if kind:
        query = query.where(Dataset.kind == kind)
    elif not include_lab:
        query = query.where(Dataset.kind != "lab")
    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Dataset.name).like(pattern), func.lower(Dataset.description).like(pattern)))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(Dataset.updated_at.desc(), Dataset.name).limit(limit).offset(offset))
    return Page(items=[dataset_out(session, d) for d in rows], total=total, limit=limit, offset=offset)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, session: Session = Depends(get_db)) -> DatasetOut:
    return dataset_out(session, svc.get_dataset(session, dataset_id))


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(dataset_id: str, body: DatasetUpdate, session: Session = Depends(get_db)) -> DatasetOut:
    dataset = svc.get_dataset(session, dataset_id)
    if body.name is not None and body.name != dataset.name:
        name = svc.validate_dataset_name(body.name)
        if session.scalar(select(Dataset).where(Dataset.name == name, Dataset.id != dataset.id)):
            raise ConflictError(f"A dataset named '{name}' already exists")
        dataset.name = name
    if body.description is not None:
        dataset.description = body.description.strip()
    session.flush()
    return dataset_out(session, dataset)


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str, session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, object]:
    """Permanently delete a dataset, all of its versions, stored files, rules, results and lab data."""
    dataset = svc.get_dataset(session, dataset_id)
    removed = svc.delete_dataset(session, settings, dataset)
    return {"deleted": True, "dataset_id": dataset_id, "files_removed": removed}


@router.get("/{dataset_id}/versions", response_model=list[VersionOut])
def list_versions(dataset_id: str, session: Session = Depends(get_db)) -> list[VersionOut]:
    dataset = svc.get_dataset(session, dataset_id)
    return [VersionOut.model_validate(v) for v in svc.list_versions(session, dataset.id)]


@router.get("/{dataset_id}/versions/{version_id}", response_model=VersionOut)
def get_version(dataset_id: str, version_id: str, session: Session = Depends(get_db)) -> VersionOut:
    dataset = svc.get_dataset(session, dataset_id)
    return VersionOut.model_validate(svc.get_version(session, dataset, version_id))


@router.get("/{dataset_id}/versions/{version_id}/summary")
def get_import_summary(dataset_id: str, version_id: str, session: Session = Depends(get_db)) -> dict[str, object]:
    dataset = svc.get_dataset(session, dataset_id)
    return svc.get_version(session, dataset, version_id).import_summary


@router.delete("/{dataset_id}/versions/{version_id}")
def delete_version(
    dataset_id: str, version_id: str, session: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, object]:
    dataset = svc.get_dataset(session, dataset_id)
    version = svc.get_version(session, dataset, version_id)
    if (
        session.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id))
        == 1
    ):
        raise ConflictError("Cannot delete the only version; delete the dataset instead.")
    svc.delete_version(session, settings, version)
    return {"deleted": True, "version_id": version_id}


@router.post("/{dataset_id}/versions/{version_id}/quarantine", response_model=VersionOut)
def quarantine_version(
    dataset_id: str, version_id: str, body: QuarantineRequest, session: Session = Depends(get_db)
) -> VersionOut:
    """Mark a version as quarantined. Data is kept; the previous active version becomes current."""
    dataset = svc.get_dataset(session, dataset_id)
    version = svc.get_version(session, dataset, version_id)
    version.status = "quarantined"
    version.status_reason = body.reason.strip() or "Quarantined by user"
    session.flush()
    return VersionOut.model_validate(version)


@router.post("/{dataset_id}/versions/{version_id}/release", response_model=VersionOut)
def release_version(dataset_id: str, version_id: str, session: Session = Depends(get_db)) -> VersionOut:
    dataset = svc.get_dataset(session, dataset_id)
    version = svc.get_version(session, dataset, version_id)
    version.status = "active"
    version.status_reason = ""
    session.flush()
    return VersionOut.model_validate(version)


@router.get("/{dataset_id}/preview", response_model=PreviewOut)
def preview(
    dataset_id: str,
    version_id: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> PreviewOut:
    """Paginated view of the parsed rows (original text values; missing values are null)."""
    dataset = svc.get_dataset(session, dataset_id)
    version = svc.resolve_version(session, dataset, version_id)
    limit = min(limit, settings.preview_max_page_size)
    table = svc.load_table(settings, version)
    page = table.raw.iloc[offset : offset + limit]
    rows = [[None if v is None else str(v) for v in record] for record in page.itertuples(index=False, name=None)]
    return PreviewOut(
        dataset_id=dataset.id,
        version_id=version.id,
        columns=[ColumnSchema(**c) for c in table.schema],
        rows=rows,
        row_numbers=[int(i) + 1 for i in page.index],
        total=len(table.raw),
        offset=offset,
        limit=limit,
    )


@router.get("/{dataset_id}/profile", response_model=ProfileOut)
def get_profile(
    dataset_id: str,
    version_id: str | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> ProfileOut:
    """Exact column statistics for a version (defaults to the current version). Cached per version."""
    dataset = svc.get_dataset(session, dataset_id)
    version = svc.resolve_version(session, dataset, version_id)
    stored, cached = get_or_compute_profile(session, settings, version)
    return ProfileOut(
        dataset_id=dataset.id,
        version_id=version.id,
        version_number=version.version_number,
        computed_at=stored.computed_at,
        duration_ms=round(stored.duration_ms, 2),
        cached=cached,
        profile=stored.profile,
    )


@router.get("/{dataset_id}/rejected-rows", response_model=RejectedRowsOut)
def rejected_rows(
    dataset_id: str, version_id: str | None = None, session: Session = Depends(get_db)
) -> RejectedRowsOut:
    dataset = svc.get_dataset(session, dataset_id)
    version = svc.resolve_version(session, dataset, version_id)
    summary = version.import_summary
    return RejectedRowsOut(
        version_id=version.id,
        total=version.rejected_row_count,
        truncated=bool(summary.get("rejected_rows_truncated")),
        rows=summary.get("rejected_rows", []),
    )
