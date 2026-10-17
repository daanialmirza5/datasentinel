from tests.conftest import make_settings
from tests.helpers import ORDERS_CSV, import_ok, sample_bytes, upload


def test_import_creates_dataset_version_and_summary(client):
    body = import_ok(client, ORDERS_CSV, dataset_name="orders")
    assert body["dataset"]["name"] == "orders"
    assert body["dataset"]["asset_id"]
    version = body["version"]
    assert version["version_number"] == 1
    assert version["row_count"] == 4 and version["column_count"] == 3
    assert {c["name"]: c["type"] for c in version["schema"]} == {
        "order_id": "integer",
        "amount": "float",
        "status": "string",
    }
    assert body["summary"]["missing_cells"] == 1
    assert len(version["sha256"]) == 64


def test_second_import_becomes_version_two_and_preserves_first(client):
    first = import_ok(client, ORDERS_CSV, dataset_name="orders")
    ds_id = first["dataset"]["id"]
    second = import_ok(client, ORDERS_CSV + b"5,99.0,paid\n", dataset_id=ds_id)
    assert second["version"]["version_number"] == 2
    versions = client.get(f"/api/v1/datasets/{ds_id}/versions").json()
    assert [v["row_count"] for v in versions] == [4, 5]
    assert versions[0]["sha256"] == first["version"]["sha256"]


def test_identical_reupload_is_flagged(client):
    first = import_ok(client, ORDERS_CSV, dataset_name="orders")
    second = import_ok(client, ORDERS_CSV, dataset_id=first["dataset"]["id"])
    assert any("byte-identical" in w for w in second["summary"]["warnings"])


def test_duplicate_dataset_name_conflicts(client):
    import_ok(client, ORDERS_CSV, dataset_name="orders")
    response = upload(client, ORDERS_CSV, dataset_name="orders")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_unsupported_extension_is_415(client):
    response = upload(client, b"MZ...", filename="evil.exe")
    assert response.status_code == 415


def test_malformed_json_is_422_with_message(client):
    response = upload(client, b"[{bad json", filename="x.json")
    assert response.status_code == 422
    assert "Malformed JSON" in response.json()["error"]["message"]


def test_path_traversal_filename_is_display_only(client, settings):
    body = import_ok(client, ORDERS_CSV, filename="..\\..\\windows\\evil.csv")
    assert body["version"]["original_filename"] == "evil.csv"
    assert body["dataset"]["name"] == "evil"
    stored = list(settings.storage_dir.iterdir())
    assert len(stored) == 1 and stored[0].name.startswith("ver_")


def test_upload_size_limit_returns_413(tmp_path):
    from fastapi.testclient import TestClient

    from datasentinel.main import create_app

    app = create_app(make_settings(tmp_path, max_upload_mb=0.01))
    with TestClient(app) as small_client:
        response = upload(small_client, b"a\n" + b"1\n" * 20000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert not any((tmp_path / "storage").iterdir())


def test_preview_pagination_and_rejected_rows(client):
    content = b"a,b\n" + b"".join(f"{i},{i * 2}\n".encode() for i in range(120)) + b"bad\n"
    body = import_ok(client, content, dataset_name="paged")
    ds_id = body["dataset"]["id"]
    page = client.get(f"/api/v1/datasets/{ds_id}/preview", params={"offset": 100, "limit": 50}).json()
    assert page["total"] == 120
    assert len(page["rows"]) == 20
    assert page["rows"][0] == ["100", "200"]
    assert page["row_numbers"][0] == 101
    rejected = client.get(f"/api/v1/datasets/{ds_id}/rejected-rows").json()
    assert rejected["total"] == 1
    assert rejected["rows"][0]["line"] == 122


def test_preview_page_size_is_capped(client):
    body = import_ok(client, ORDERS_CSV, dataset_name="orders")
    response = client.get(f"/api/v1/datasets/{body['dataset']['id']}/preview", params={"limit": 5000})
    assert response.status_code == 422


def test_list_filter_and_lookup_errors(client):
    import_ok(client, ORDERS_CSV, dataset_name="orders")
    import_ok(client, sample_bytes("products.json"), filename="products.json")
    listing = client.get("/api/v1/datasets", params={"q": "prod"}).json()
    assert listing["total"] == 1 and listing["items"][0]["name"] == "products"
    assert client.get("/api/v1/datasets/ds_missing").status_code == 404


def test_quarantine_makes_previous_version_current(client):
    first = import_ok(client, ORDERS_CSV, dataset_name="orders")
    ds_id = first["dataset"]["id"]
    second = import_ok(client, ORDERS_CSV + b"5,1.0,paid\n", dataset_id=ds_id)
    response = client.post(
        f"/api/v1/datasets/{ds_id}/versions/{second['version']['id']}/quarantine", json={"reason": "bad export"}
    )
    assert response.json()["status"] == "quarantined"
    dataset = client.get(f"/api/v1/datasets/{ds_id}").json()
    assert dataset["current_version"]["id"] == first["version"]["id"]
    client.post(f"/api/v1/datasets/{ds_id}/versions/{second['version']['id']}/release")
    assert client.get(f"/api/v1/datasets/{ds_id}").json()["current_version"]["id"] == second["version"]["id"]


def test_delete_dataset_removes_files(client, settings):
    body = import_ok(client, ORDERS_CSV, dataset_name="orders")
    ds_id = body["dataset"]["id"]
    assert any(settings.storage_dir.iterdir())
    response = client.delete(f"/api/v1/datasets/{ds_id}")
    assert response.json() == {"deleted": True, "dataset_id": ds_id, "files_removed": 1}
    assert not any(settings.storage_dir.iterdir())
    assert client.get(f"/api/v1/datasets/{ds_id}").status_code == 404


def test_all_sample_files_import(client):
    for name in ["customers.csv", "orders_2026_07.csv", "products.json", "sensor_readings.jsonl"]:
        body = import_ok(client, sample_bytes(name), filename=name)
        assert body["version"]["rejected_row_count"] == 0, name
    products = client.get("/api/v1/datasets", params={"q": "products"}).json()["items"][0]
    types = {c["name"]: c["type"] for c in products["current_version"]["schema"]}
    assert types["dimensions.weight_kg"] == "float"
    assert types["in_stock"] == "boolean"
    assert types["launched_on"] == "datetime"


def test_import_accepts_format_aliases(client):
    body = import_ok(client, b'{"id": 1, "v": "a"}\n{"id": 2, "v": "b"}\n', "export.txt", file_format="NDJSON")
    assert body["version"]["file_format"] == "jsonl"
