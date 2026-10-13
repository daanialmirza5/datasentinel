"""Post-import analysis pipeline.

Called once for every newly imported version, inside the import transaction, so that a version is
never visible without its analysis results.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from datasentinel.config import Settings
from datasentinel.models import DatasetVersion
from datasentinel.services.datasets import previous_version
from datasentinel.services.drift import get_or_compute_drift
from datasentinel.services.profiles import get_or_compute_profile
from datasentinel.services.validation import enabled_rules, run_validation


def analyze_new_version(session: Session, settings: Settings, version: DatasetVersion) -> None:
    """Profile the version, run the dataset's enabled rules and compare it with the previous version."""
    get_or_compute_profile(session, settings, version)
    if enabled_rules(session, version.dataset_id):
        run_validation(session, settings, version.dataset, version, trigger="import")
    base = previous_version(session, version)
    if base is not None:
        get_or_compute_drift(session, settings, base, version)
