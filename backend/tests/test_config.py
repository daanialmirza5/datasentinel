"""Environment-based settings parsing."""

import pytest
from pydantic import ValidationError

from datasentinel.config import Settings


def test_cors_origins_accept_comma_separated_values(tmp_path):
    settings = Settings(data_dir=tmp_path, cors_origins=" http://a.test , http://b.test,, ")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_drop_trailing_slashes(tmp_path):
    settings = Settings(data_dir=tmp_path, cors_origins='["http://a.test/", "http://b.test"]')
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_log_level_is_normalised(tmp_path):
    assert Settings(data_dir=tmp_path, log_level=" debug ").log_level == "DEBUG"


def test_unknown_log_level_is_rejected(tmp_path):
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, log_level="LOUD")
