"""Environment-based configuration.

Every setting can be supplied through an environment variable prefixed with ``DATASENTINEL_``
(for example ``DATASENTINEL_MAX_UPLOAD_MB=50``) or through a ``.env`` file in the working
directory. Nothing here is a secret by default; the optional PostgreSQL URL may contain
credentials and must therefore only ever come from the environment.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DATASENTINEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DataSentinel"
    environment: str = Field(default="development", pattern=r"^(development|test|production)$")

    # Storage
    data_dir: Path = BACKEND_ROOT / "var"
    database_url: str | None = None  # defaults to SQLite inside data_dir

    # HTTP
    # Comma-separated in the environment; NoDecode stops pydantic-settings from requiring JSON.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: str = "INFO"

    # Resource limits
    max_upload_mb: float = Field(default=25.0, gt=0, le=500)
    max_rows: int = Field(default=200_000, gt=0)
    max_columns: int = Field(default=200, gt=0)
    max_cell_chars: int = Field(default=10_000, gt=0)
    max_versions_per_dataset: int = Field(default=50, gt=0)
    preview_max_page_size: int = Field(default=200, gt=0, le=1000)
    rule_example_limit: int = Field(default=5, ge=0, le=50)
    regex_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    # Retention
    experiment_retention_hours: int = Field(default=24, ge=0)  # 0 disables automatic expiry

    # Startup behaviour
    auto_migrate: bool = True
    load_samples_on_startup: bool = False
    # Public read-only demo: refuse uploads and edits, keep the fault lab and reports usable.
    demo_mode: bool = False
    # Serve a built frontend (frontend/dist) from the API process, for single-container deployments.
    static_dir: Path | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'datasentinel.db').as_posix()}"

    @property
    def database_backend(self) -> str:
        return self.resolved_database_url.split(":", 1)[0].split("+", 1)[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
