"""Security, privacy and resource-limit behaviour."""

import http.client
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from datasentinel.main import create_app
from tests.conftest import make_settings
from tests.helpers import ORDERS_CSV, import_ok, upload


def test_declared_oversized_body_is_rejected_before_reading(tmp_path):
    app = create_app(make_settings(tmp_path, max_upload_mb=0.01))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/datasets/import",
            content=b"x" * 10,
            headers={"Content-Length": str(50 * 1024 * 1024), "Content-Type": "text/csv"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_invalid_content_length_is_rejected(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/v1/reports", content=b"{}", headers={"Content-Length": "abc"})
    assert response.status_code == 400


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_chunked_upload_without_length_is_cut_off(tmp_path):
    """A chunked body has no Content-Length; the limit must be enforced while streaming."""
    app = create_app(make_settings(tmp_path, max_upload_mb=0.05))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        boundary = "XBOUNDARY"
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode()

        def body():
            yield head
            for _ in range(200):
                yield b"a,b\n" * 256  # ~200 KB total, well above the 50 KB limit
            yield f"\r\n--{boundary}--\r\n".encode()

        conn.request(
            "POST",
            "/api/v1/datasets/import",
            body=body(),
            encode_chunked=True,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Transfer-Encoding": "chunked"},
        )
        response = conn.getresponse()
        assert response.status == 413
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not any((tmp_path / "storage").glob("ver_*"))


def test_unexpected_errors_do_not_leak_internals(tmp_path, monkeypatch):
    app = create_app(make_settings(tmp_path))

    def boom(*_args, **_kwargs):
        raise RuntimeError("secret path C:\\internal\\db.sqlite and SELECT * FROM users")

    monkeypatch.setattr("datasentinel.api.system.impact_summary", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/dashboard")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret" not in response.text and "SELECT" not in response.text
    assert body["request_id"]


def test_validation_errors_are_structured(client):
    response = client.get("/api/v1/datasets", params={"limit": 0})
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert details[0]["location"] == ["query", "limit"]


def test_unknown_fields_are_rejected(client):
    ds = import_ok(client, ORDERS_CSV, dataset_name="orders")["dataset"]
    response = client.post(
        f"/api/v1/datasets/{ds['id']}/rules",
        json={"name": "x", "rule_type": "row_count", "params": {"min": 1}, "sql": "DROP TABLE"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("name", ["../../etc", "<script>alert(1)</script>", "a" * 200, "", "  "])
def test_dataset_names_are_validated(client, name):
    response = upload(client, ORDERS_CSV, dataset_name=name)
    if name.strip() == "":
        # Blank names fall back to the (sanitised) file name.
        assert response.status_code == 201
    else:
        assert response.status_code == 422


def test_integrity_check_detects_tampered_and_missing_files(client, settings):
    first = import_ok(client, ORDERS_CSV, dataset_name="orders")
    second = import_ok(client, b"a\n1\n", dataset_name="other")
    assert client.post("/api/v1/maintenance/integrity").json()["ok"] is True
    (settings.storage_dir / f"{first['version']['id']}.csv").write_bytes(b"tampered\n")
    (settings.storage_dir / f"{second['version']['id']}.csv").unlink()
    (settings.storage_dir / "ver_ffffffffffffffff.csv").write_bytes(b"stray")
    report = client.post("/api/v1/maintenance/integrity").json()
    assert report["ok"] is False
    assert [c["version_id"] for c in report["files"]["corrupted"]] == [first["version"]["id"]]
    assert [m["version_id"] for m in report["files"]["missing"]] == [second["version"]["id"]]
    assert report["files"]["orphaned"] == ["ver_ffffffffffffffff.csv"]
    assert report["database"]["ok"] is True


def test_demo_mode_blocks_uploads_and_edits_but_allows_the_lab(tmp_path):
    app = create_app(make_settings(tmp_path, demo_mode=True, load_samples_on_startup=True))
    with TestClient(app) as client:
        assert client.get("/api/v1/settings").json()["demo_mode"] is True
        blocked = upload(client, ORDERS_CSV, dataset_name="mine")
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "demo_mode"
        orders = next(d for d in client.get("/api/v1/datasets").json()["items"] if d["name"] == "orders")
        assert client.delete(f"/api/v1/datasets/{orders['id']}").status_code == 403
        assert client.post("/api/v1/lineage/assets", json={"name": "x", "kind": "report"}).status_code == 403
        exp = client.post("/api/v1/experiments", json={"dataset_id": orders["id"], "fault_type": "missing_values"})
        assert exp.status_code == 201
        assert client.post("/api/v1/reports", json={"dataset_id": orders["id"]}).status_code == 201
        assert client.delete(f"/api/v1/experiments/{exp.json()['id']}").status_code == 200


def test_uploaded_content_is_never_executed(client, settings):
    payload = b"name,cmd\n=cmd|'/C calc'!A0,__import__('os').system('echo pwned')\n"
    body = import_ok(client, payload, dataset_name="evil")
    preview = client.get(f"/api/v1/datasets/{body['dataset']['id']}/preview").json()
    assert preview["rows"][0] == ["=cmd|'/C calc'!A0", "__import__('os').system('echo pwned')"]
    assert not (settings.data_dir / "pwned").exists()
