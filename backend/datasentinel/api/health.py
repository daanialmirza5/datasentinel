from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from datasentinel import __version__
from datasentinel.db import migration_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    """Readiness: the database answers, migrations are current and storage is writable."""
    checks: dict[str, dict[str, Any]] = {}

    try:
        status = migration_status(request.app.state.engine)
        checks["database"] = {"ok": True}
        checks["migrations"] = {"ok": bool(status["up_to_date"]), "current": status["current"], "head": status["head"]}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        checks["migrations"] = {"ok": False}

    storage_dir = request.app.state.settings.storage_dir
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=storage_dir, prefix=".ready-")
        os.close(fd)
        os.remove(probe)
        checks["storage"] = {"ok": True}
    except OSError as exc:
        checks["storage"] = {"ok": False, "error": type(exc).__name__}

    is_ready = all(check["ok"] for check in checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503, content={"status": "ready" if is_ready else "not_ready", "checks": checks}
    )
