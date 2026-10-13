from __future__ import annotations

from fastapi import Request

from datasentinel.config import Settings
from datasentinel.db import get_db

__all__ = ["get_db", "get_settings_dep"]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings
