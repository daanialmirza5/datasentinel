from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient

from datasentinel.main import create_app
from datasentinel.models import Base
from tests.conftest import make_settings


def test_health_reports_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "x-request-id" in response.headers


def test_well_formed_incoming_request_id_is_reused(client):
    response = client.get("/api/v1/does-not-exist", headers={"X-Request-ID": "proxy-abc12345"})
    assert response.headers["x-request-id"] == "proxy-abc12345"
    assert response.json()["request_id"] == "proxy-abc12345"


def test_malformed_incoming_request_id_is_replaced(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\twith<script>"})
    assert response.headers["x-request-id"] != "bad id\twith<script>"
    assert len(response.headers["x-request-id"]) == 16


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]


def test_ready_when_migrated(client):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["migrations"]["ok"] is True
    assert body["checks"]["migrations"]["current"] == body["checks"]["migrations"]["head"]


def test_not_ready_without_migrations(tmp_path):
    app = create_app(make_settings(tmp_path, auto_migrate=False))
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"]["ok"] is False


def test_migrations_match_models(client):
    engine = client.app.state.engine
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_cors_allows_only_configured_origins(client):
    allowed = client.options(
        "/api/v1/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    denied = client.options(
        "/api/v1/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in denied.headers


def test_serves_built_frontend_with_spa_fallback(tmp_path):
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    app = create_app(make_settings(tmp_path / "data", static_dir=static))
    with TestClient(app) as client:
        assert client.get("/assets/app.js").text == "console.log(1)"
        deep = client.get("/lineage?dataset=x")
        assert deep.text == "<html>app</html>" and "frame-ancestors 'none'" in deep.headers["content-security-policy"]
        assert client.get("/../secret.txt").text != "nope"
        assert client.get("/api/v1/nope").json()["error"]["code"] == "not_found"
        assert client.get("/api/v1/health").json()["status"] == "ok"


def test_settings_parse_comma_separated_environment_values(monkeypatch, tmp_path):
    """Regression: list settings must accept the documented comma-separated form, not only JSON."""
    from datasentinel.config import Settings

    monkeypatch.setenv("DATASENTINEL_CORS_ORIGINS", "http://localhost:8000, https://demo.example")
    monkeypatch.setenv("DATASENTINEL_DEMO_MODE", "true")
    settings = Settings(data_dir=tmp_path)
    assert settings.cors_origins == ["http://localhost:8000", "https://demo.example"]
    assert settings.demo_mode is True
    monkeypatch.setenv("DATASENTINEL_CORS_ORIGINS", '["https://json.example"]')
    assert Settings(data_dir=tmp_path).cors_origins == ["https://json.example"]
