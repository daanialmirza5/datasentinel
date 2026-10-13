"""Integrity verification: database consistency and stored-file checksums."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.models import DatasetVersion
from datasentinel.services.datasets import storage_for
from datasentinel.storage import StorageError


def check_integrity(session: Session, settings: Settings) -> dict[str, Any]:
    """Verify the database and that every version's stored file exists and matches its SHA-256.

    Nothing is repaired or deleted automatically; problems are reported for a person to act on.
    """
    database: dict[str, Any]
    if settings.database_backend == "sqlite":
        rows = [r[0] for r in session.execute(text("PRAGMA integrity_check")).all()]
        fk_violations = session.execute(text("PRAGMA foreign_key_check")).all()
        database = {
            "ok": rows == ["ok"] and not fk_violations,
            "integrity_check": rows[:20],
            "foreign_key_violations": len(fk_violations),
        }
    else:
        session.execute(text("SELECT 1"))
        database = {"ok": True, "note": "Server-side integrity is managed by the database engine."}

    storage = storage_for(settings)
    missing, corrupted, checked = [], [], 0
    known = set()
    for version in session.scalars(select(DatasetVersion)):
        known.add(version.storage_key)
        checked += 1
        try:
            content = storage.read(version.storage_key)
        except StorageError:
            missing.append({"version_id": version.id, "dataset_id": version.dataset_id})
            continue
        if hashlib.sha256(content).hexdigest() != version.sha256:
            corrupted.append({"version_id": version.id, "dataset_id": version.dataset_id})
    orphans = []
    if storage.root.exists():
        orphans = sorted(
            p.name for p in storage.root.iterdir() if p.is_file() and not p.name.startswith(".") and p.name not in known
        )
    return {
        "ok": database["ok"] and not missing and not corrupted,
        "database": database,
        "files": {"checked": checked, "missing": missing, "corrupted": corrupted, "orphaned": orphans},
    }
