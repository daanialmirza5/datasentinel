"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from datasentinel import __version__
from datasentinel.api import datasets, drift, experiments, health, lineage, reports, rules, system
from datasentinel.config import Settings, get_settings
from datasentinel.db import build_engine, make_session_factory, run_migrations, session_scope
from datasentinel.demo_mode import DemoModeMiddleware
from datasentinel.errors import install_error_handlers
from datasentinel.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from datasentinel.models import Dataset
from datasentinel.samples.workspace import load_demo_workspace
from datasentinel.services.experiments import purge_expired

API_PREFIX = "/api/v1"
logger = logging.getLogger("datasentinel")


def _startup_tasks(app: FastAPI, settings: Settings) -> None:
    """Apply retention and optionally seed the demo workspace into an empty database."""
    with session_scope(app.state.session_factory) as session:
        removed = purge_expired(session, settings)
        if removed:
            logger.info("Retention: removed %d expired experiment(s)", removed)
        if settings.load_samples_on_startup and session.scalar(select(func.count()).select_from(Dataset)) == 0:
            summary = load_demo_workspace(session, settings)
            logger.info("Loaded demo workspace: %s datasets, %s versions", summary["datasets"], summary["versions"])


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            run_migrations(engine)
            _startup_tasks(app, settings)
        yield
        engine.dispose()

    app = FastAPI(
        title="DataSentinel API",
        version=__version__,
        description="Explainable data observability: ingestion, profiling, quality rules, schema drift, "
        "statistical anomalies, lineage impact and fault-injection experiments.",
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    install_error_handlers(app)
    # Upload bodies may carry multipart overhead on top of the file itself.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + 64 * 1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Accept"],
        allow_credentials=False,
        expose_headers=["X-Request-Id", "Content-Disposition"],
    )
    if settings.demo_mode:
        app.add_middleware(DemoModeMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(datasets.router, prefix=API_PREFIX)
    app.include_router(rules.router, prefix=API_PREFIX)
    app.include_router(drift.router, prefix=API_PREFIX)
    app.include_router(lineage.router, prefix=API_PREFIX)
    app.include_router(experiments.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(system.router, prefix=API_PREFIX)
    return app


app = create_app()
