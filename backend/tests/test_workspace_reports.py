from datetime import timedelta

from datasentinel.models import Experiment, utcnow
from datasentinel.services.reports import render_markdown
from tests.helpers import import_ok


def load_demo(client) -> dict:
    response = client.post("/api/v1/samples/load")
    assert response.status_code == 201, response.text
    return response.json()


def dataset_by_name(client, name):
    return next(d for d in client.get("/api/v1/datasets").json()["items"] if d["name"] == name)


def test_demo_workspace_loads_and_surfaces_planted_issues(client):
    summary = load_demo(client)
    assert summary["datasets"] == 5 and summary["versions"] == 7 and summary["edges"] == 10
    assert client.post("/api/v1/samples/load").status_code == 409

    orders = dataset_by_name(client, "orders")
    assert orders["version_count"] == 3 and orders["kind"] == "sample"
    runs = client.get(f"/api/v1/datasets/{orders['id']}/validations").json()
    latest = client.get(f"/api/v1/validations/{runs[0]['id']}").json()
    failed = {r["rule_name"] for r in latest["results"] if r["status"] == "failed"}
    assert {
        "order_id unique",
        "currency values",
        "amount range",
        "discount present",
        "ship_country mostly filled",
    } <= failed
    # The July and August exports are clean against the same rules.
    first_runs = [r for r in runs if r["version_number"] in (1, 2)]
    assert all(r["summary"]["failed"] == 0 for r in first_runs)

    sensors = dataset_by_name(client, "sensor_readings")
    sensor_run = client.get(f"/api/v1/datasets/{sensors['id']}/validations").json()[0]
    assert sensor_run["summary"]["failed"] == 1  # the stuck 85.0 °C readings

    graph = client.get("/api/v1/lineage").json()
    assert len(graph["nodes"]) == 12 and graph["cycles"] == []
    sensor_node = next(n for n in graph["nodes"] if n["name"] == "sensor_readings")
    assert sensor_node["upstream_count"] == 0 and sensor_node["downstream_count"] == 0  # disconnected


def test_dashboard_numbers_come_from_stored_results(client):
    empty = client.get("/api/v1/dashboard").json()
    assert empty["dataset_count"] == 0 and empty["active_anomalies"]["count"] == 0
    load_demo(client)
    board = client.get("/api/v1/dashboard").json()
    assert board["dataset_count"] == 5 and board["version_count"] == 7
    assert board["rule_status"]["failed"] >= 5
    assert board["rule_status"]["datasets_failing"] == 2  # orders and sensor_readings
    assert board["active_anomalies"]["count"] >= 6
    assert {c["change_type"] for c in board["schema_changes"]["items"]} >= {"removed", "added", "likely_rename"}
    impacted = {i["name"]: i["classification"] for i in board["impact"]["impacted"]}
    assert impacted["Revenue aggregation job"] == "suspected_impact"
    assert impacted["Executive revenue dashboard"] == "unverified_risk"
    assert board["recent_imports"][0]["dataset_name"] in {"sensor_readings", "daily_revenue"}


def test_settings_disclose_limits_and_privacy_without_secrets(client):
    body = client.get("/api/v1/settings").json()
    assert body["privacy"]["external_services"] == []
    assert body["limits"]["max_upload_mb"] == 25
    assert body["database_backend"] == "sqlite"
    assert "database_url" not in body and "sqlite:///" not in str(body)


def test_dataset_report_json_and_markdown_export(client):
    load_demo(client)
    orders = dataset_by_name(client, "orders")
    created = client.post("/api/v1/reports", json={"dataset_id": orders["id"]})
    assert created.status_code == 201
    report = created.json()
    content = report["content"]
    assert content["version"]["version_number"] == 3
    assert content["drift"]["status"] == "compared" and content["drift"]["base_version"]["version_number"] == 2
    assert content["quality"]["summary"]["failed"] >= 5
    assert content["impact"]["origin_state"] == "failing"
    assert content["recommendations"][0]["kind"] == "contain"

    markdown = client.get(f"/api/v1/reports/{report['id']}/export", params={"format": "markdown"})
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in markdown.headers["content-disposition"]
    text = markdown.text
    for heading in ("## Quality rules", "## Drift findings", "## Downstream impact", "## Recommended actions"):
        assert heading in text
    as_json = client.get(f"/api/v1/reports/{report['id']}/export", params={"format": "json"})
    assert as_json.json()["report_id"] == report["id"]
    assert client.get("/api/v1/reports").json()["total"] == 1


def test_report_requires_exactly_one_target(client):
    assert client.post("/api/v1/reports", json={}).status_code == 422
    assert client.post("/api/v1/reports", json={"dataset_id": "a", "experiment_id": "b"}).status_code == 422
    assert client.post("/api/v1/reports", json={"dataset_id": "ds_missing"}).status_code == 404


def test_markdown_escapes_table_breaking_content():
    content = {
        "kind": "dataset",
        "title": "x | y",
        "generated_at": "now",
        "generator": "test",
        "dataset": {"name": "evil|name"},
        "version": None,
        "profile_summary": {
            "row_count": 1,
            "column_count": 1,
            "duplicate_rows": 0,
            "missing_pct": 0.0,
            "columns": [{"name": "a|b\nc", "type": "string", "null_pct": 0.0, "distinct_count": 1, "invalid_count": 0}],
        },
        "quality": {"status": "no_rules", "message": "none"},
        "anomalies": {"signals": []},
        "drift": {"status": "no_baseline", "message": "n/a"},
        "impact": None,
        "recommendations": [],
        "disclaimer": "d",
    }
    text = render_markdown(content)
    assert "| a\\|b c | string |" in text


def test_retention_purges_expired_lab_data_only(client, session_factory):
    from tests.lab_fixtures import orders_workspace, run_fault

    workspace = orders_workspace(client)
    exp = run_fault(client, workspace["orders"]["id"], "missing_values")
    with session_factory() as session:
        session.get(Experiment, exp["id"]).expires_at = utcnow() - timedelta(minutes=1)
        session.commit()
    assert client.post("/api/v1/maintenance/retention").json() == {"expired_experiments_removed": 1}
    assert client.get(f"/api/v1/datasets/{exp['lab_dataset_id']}").status_code == 404
    assert client.get(f"/api/v1/datasets/{workspace['orders']['id']}").status_code == 200


def test_end_to_end_import_to_report(client):
    """Import → profile → rule → inject fault → detect → compare → trace impact → export report."""
    customers = import_ok(client, b"customer_id\n1\n2\n3\n", dataset_name="customers")["dataset"]
    rows = "".join(f"{i},{(i % 3) + 1},{10 + i % 7}.5,{'paid' if i % 4 else 'refunded'}\n" for i in range(400))
    orders = import_ok(client, ("order_id,customer_id,amount,status\n" + rows).encode(), dataset_name="orders")[
        "dataset"
    ]

    profile = client.get(f"/api/v1/datasets/{orders['id']}/profile").json()["profile"]
    assert next(c for c in profile["columns"] if c["name"] == "amount")["type"] == "float"

    client.post(
        f"/api/v1/datasets/{orders['id']}/rules",
        json={
            "name": "status values",
            "rule_type": "allowed_values",
            "column_name": "status",
            "severity": "high",
            "params": {"values": ["paid", "refunded"]},
        },
    )
    assert client.post(f"/api/v1/datasets/{orders['id']}/validate").json()["summary"]["health"] == "passing"

    report_asset = client.post("/api/v1/lineage/assets", json={"name": "finance report", "kind": "report"}).json()
    client.post("/api/v1/lineage/edges", json={"source_id": orders["asset_id"], "target_id": report_asset["id"]})

    exp = client.post(
        "/api/v1/experiments",
        json={
            "dataset_id": orders["id"],
            "fault_type": "unexpected_categories",
            "seed": 1,
            "params": {"column": "status", "fraction": 0.1},
        },
    ).json()
    assert exp["evaluation"]["detected"] is True
    assert {s["source"] for s in exp["evaluation"]["true_positives"]} == {"statistics", "rule"}
    comparison = next(c for c in exp["detection"]["column_comparisons"] if c["column"] == "status")
    assert comparison["categories"]["new_values"] == {"UNKNOWN_CODE": 40}
    impacted = exp["evaluation"]["simulated_impact"]["impacted"]
    assert impacted[0]["name"] == "finance report" and impacted[0]["classification"] == "suspected_impact"

    report = client.post("/api/v1/reports", json={"experiment_id": exp["id"]}).json()
    exported = client.get(f"/api/v1/reports/{report['id']}/export").text
    assert "## Ground truth" in exported and "**detected**" in exported and "finance report" in exported
    assert customers["id"]
