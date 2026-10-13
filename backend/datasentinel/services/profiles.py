"""Profile persistence: compute once per version and algorithm version, then reuse."""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.models import DatasetVersion, VersionProfile, utcnow
from datasentinel.profiling import ALGORITHM_VERSION, profile_table
from datasentinel.services.datasets import load_table


def get_or_compute_profile(
    session: Session, settings: Settings, version: DatasetVersion
) -> tuple[VersionProfile, bool]:
    """Return (profile, was_cached)."""
    stored = session.get(VersionProfile, version.id)
    if stored is not None and stored.algorithm_version == ALGORITHM_VERSION:
        return stored, True
    started = time.perf_counter()
    profile = profile_table(load_table(settings, version))
    duration = (time.perf_counter() - started) * 1000
    if stored is None:
        stored = VersionProfile(
            version_id=version.id, algorithm_version=ALGORITHM_VERSION, profile=profile, duration_ms=duration
        )
        session.add(stored)
    else:
        stored.algorithm_version, stored.profile, stored.duration_ms = ALGORITHM_VERSION, profile, duration
        stored.computed_at = utcnow()
    session.flush()
    return stored, False
