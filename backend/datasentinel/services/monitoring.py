"""Post-import analysis pipeline.

Called once for every newly imported version, inside the import transaction, so that a version is
never visible without its analysis results.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.models import DatasetVersion


def analyze_new_version(session: Session, settings: Settings, version: DatasetVersion) -> None:
    """Hook for profiling, rule validation and drift analysis (added as those engines land)."""
    return None
