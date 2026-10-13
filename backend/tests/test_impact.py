from datasentinel.recommendations import build_recommendations
from tests.helpers import ORDERS_CSV, import_ok

BAD_ORDERS = ORDERS_CSV + b"5,,paid\n6,,paid\n"


def _asset(client, name, kind):
    return client.post("/api/v1/lineage/assets", json={"name": name, "kind": kind, "owner": "analytics"}).json()["id"]


def _edge(client, source, target):
    assert client.post("/api/v1/lineage/edges", json={"source_id": source, "target_id": target}).status_code == 201


def build_pipeline(client, *, fail_latest: bool):
    orders = import_ok(client, ORDERS_CSV.replace(b"3,,refunded", b"3,1.0,refunded"), dataset_name="orders")
    ds_id = orders["dataset"]["id"]
    client.post(
        f"/api/v1/datasets/{ds_id}/rules",
        json={"name": "amount present", "rule_type": "not_null", "column_name": "amount", "severity": "high"},
    )
    client.post(f"/api/v1/datasets/{ds_id}/validate")  # v1 passes
    if fail_latest:
        import_ok(client, BAD_ORDERS, dataset_id=ds_id)  # v2 fails on import
    revenue = import_ok(client, b"day,revenue\n2026-01-01,10\n", dataset_name="daily revenue")["dataset"]
    job = _asset(client, "aggregation job", "transformation")
    dashboard = _asset(client, "exec dashboard", "report")
    model = _asset(client, "forecast model", "model")
    _edge(client, orders["dataset"]["asset_id"], job)
    _edge(client, job, revenue["asset_id"])
    _edge(client, revenue["asset_id"], dashboard)
    _edge(client, revenue["asset_id"], model)
    return orders["dataset"], revenue


def test_failing_origin_classifies_direct_and_transitive_impact(client):
    orders, _ = build_pipeline(client, fail_latest=True)
    impact = client.get(f"/api/v1/lineage/{orders['asset_id']}/impact").json()
    assert impact["origin_state"] == "failing"
    by_name = {i["name"]: i for i in impact["impacted"]}
    assert by_name["aggregation job"]["classification"] == "suspected_impact"
    assert by_name["aggregation job"]["distance"] == 1
    assert by_name["exec dashboard"]["classification"] == "unverified_risk"
    assert by_name["exec dashboard"]["path"] == ["orders", "aggregation job", "daily revenue", "exec dashboard"]
    assert [i["name"] for i in impact["direct"]] == ["aggregation job"]
    assert {i["name"] for i in impact["transitive"]} == {"daily revenue", "exec dashboard", "forecast model"}
    assert impact["counts"]["confirmed_failure"] == 0
    assert all(i["evidence"] for i in impact["impacted"])


def test_restore_candidate_and_recommendations(client):
    orders, _ = build_pipeline(client, fail_latest=True)
    impact = client.get(f"/api/v1/lineage/{orders['asset_id']}/impact").json()
    assert impact["restore_candidate"]["version_number"] == 1
    kinds = [r["kind"] for r in impact["recommendations"]]
    assert kinds[0] == "contain"  # high severity -> quarantine first
    assert {"investigate", "recover", "verify"} <= set(kinds)
    restore = next(r for r in impact["recommendations"] if r["kind"] == "recover")
    assert "version 1" in restore["title"] and restore["action"]["type"] == "quarantine_version"
    notify = next(r for r in impact["recommendations"] if r["title"].startswith("Notify"))
    assert "exec dashboard" in notify["rationale"] and "forecast model" in notify["rationale"]
    assert [r["priority"] for r in impact["recommendations"]] == list(range(1, len(kinds) + 1))


def test_quarantine_recommendation_executed_restores_previous_version(client):
    orders, _ = build_pipeline(client, fail_latest=True)
    impact = client.get(f"/api/v1/lineage/{orders['asset_id']}/impact").json()
    action = impact["recommendations"][0]["action"]
    client.post(
        f"/api/v1/datasets/{action['dataset_id']}/versions/{action['version_id']}/quarantine",
        json={"reason": "failed amount checks"},
    )
    after = client.get(f"/api/v1/lineage/{orders['asset_id']}/impact").json()
    assert after["origin"]["health"]["version_number"] == 1
    assert after["origin_state"] == "passing"
    assert all(i["classification"] == "no_known_impact" for i in after["impacted"])
    versions = client.get(f"/api/v1/datasets/{orders['id']}/versions").json()
    assert len(versions) == 2  # nothing deleted


def test_clean_origin_reports_footprint_only(client):
    orders, _ = build_pipeline(client, fail_latest=False)
    impact = client.get(f"/api/v1/lineage/{orders['asset_id']}/impact").json()
    assert impact["origin_state"] == "passing"
    assert impact["counts"]["no_known_impact"] == 4
    assert "dependency footprint" in impact["assessment"]
    assert impact["recommendations"] == []


def test_downstream_with_own_failure_is_confirmed(client):
    orders, revenue = build_pipeline(client, fail_latest=True)
    client.post(
        f"/api/v1/datasets/{revenue['id']}/rules",
        json={"name": "enough days", "rule_type": "row_count", "params": {"min": 30}, "severity": "medium"},
    )
    client.post(f"/api/v1/datasets/{revenue['id']}/validate")
    impact = client.get(f"/api/v1/lineage/{orders['asset_id']}/impact").json()
    revenue_item = next(i for i in impact["impacted"] if i["name"] == "daily revenue")
    assert revenue_item["classification"] == "confirmed_failure"
    assert any("enough days" in e for e in revenue_item["evidence"])
    summary = client.get("/api/v1/lineage/impact/summary").json()
    assert {o["name"] for o in summary["origins"]} == {"orders", "daily revenue"}
    assert {i["name"] for i in summary["impacted"]} >= {"exec dashboard", "forecast model"}


def test_recommendations_do_not_duplicate_rules_or_suggest_existing_ones():
    """Regression: a failed allowed_values rule and a new_category signal on the same column describe
    one problem; and 'add a range rule' must not be suggested when such a rule already exists."""
    health = {
        "state": "failing",
        "version_number": 2,
        "dataset_id": "ds",
        "version_id": "v",
        "failed_rules": [
            {
                "rule_name": "currency values",
                "rule_type": "allowed_values",
                "column": "currency",
                "severity": "high",
                "violation_count": 5,
                "message": "5 values not allowed",
                "recommendation": "Confirm the new values",
            }
        ],
        "breaking_changes": [],
        "anomaly_signals": [
            {
                "category": "new_category",
                "severity": "medium",
                "column": "currency",
                "title": "JPY appeared",
                "evidence": {"new_values": {"JPY": 5}},
            },
            {
                "category": "numeric_outlier",
                "severity": "high",
                "column": "amount",
                "title": "extreme amounts",
                "evidence": {},
            },
        ],
    }
    recs = build_recommendations("orders", health, [], None, existing_rules={("amount", "range")})
    titles = [r["title"] for r in recs]
    assert "Review the unexpected values in 'currency'" not in titles
    assert "Investigate failed rule 'currency values'" in titles
    assert not any(t.startswith("Add a 'range' rule") for t in titles)
    assert not any(t.startswith("Add a 'allowed_values' rule") for t in titles)
    assert "Validate the expected range of 'amount'" in titles


def test_recommendations_without_restore_point_suggest_reexport():
    health = {
        "state": "failing",
        "version_number": 1,
        "dataset_id": "ds",
        "version_id": "v",
        "failed_rules": [],
        "breaking_changes": [
            {
                "category": "column_removed",
                "severity": "high",
                "column": "price",
                "title": "Column 'price' removed",
                "evidence": {"possible_rename_to": "unit_price"},
            }
        ],
        "anomaly_signals": [],
    }
    recs = build_recommendations("orders", health, [], None)
    titles = [r["title"] for r in recs]
    assert "Re-export the data from the source after the fix" in titles
    schema = next(r for r in recs if "schema change" in r["title"])
    assert "possibly renamed to 'unit_price', unconfirmed" in schema["rationale"]
