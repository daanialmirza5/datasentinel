from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datasentinel.config import Settings
from datasentinel.main import create_app


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {"data_dir": tmp_path, "environment": "test", "log_level": "WARNING"}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(client: TestClient):
    return client.app.state.session_factory
