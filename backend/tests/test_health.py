from fastapi.testclient import TestClient

from datasentinel.config import Settings
from datasentinel.main import create_app


def test_health_reports_ok(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, environment="test"))
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "x-request-id" in response.headers


def test_unknown_route_uses_error_envelope(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, environment="test"))
    with TestClient(app) as client:
        response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]
