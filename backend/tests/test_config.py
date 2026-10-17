"""Environment-based settings parsing."""

from datasentinel.config import Settings


def test_cors_origins_accept_comma_separated_values(tmp_path):
    settings = Settings(data_dir=tmp_path, cors_origins=" http://a.test , http://b.test,, ")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_drop_trailing_slashes(tmp_path):
    settings = Settings(data_dir=tmp_path, cors_origins='["http://a.test/", "http://b.test"]')
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
