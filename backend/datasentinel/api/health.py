from __future__ import annotations

from fastapi import APIRouter

from datasentinel import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok", "version": __version__}
