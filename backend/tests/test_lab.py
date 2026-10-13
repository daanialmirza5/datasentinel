import inspect

import pytest

from datasentinel.lab import detector
from datasentinel.lab.evaluation import evaluate, evaluate_healthy
from tests.helpers import sample_bytes
from tests.lab_fixtures import orders_workspace, run_fault

ALL_FAULTS = [
    "missing_values",
    "duplicate_records",
    "numeric_outliers",
    "schema_type_change",
    "column_removal",
    "unexpected_categories",
    "row_count_reduction",
    "timestamp_corruption",
    "referential_integrity",
    "distribution_shift",
]


@pytest.fixture
def workspace(client):
    return orders_workspace(client)


@pytest.mark.parametrize("fault", ALL_FAULTS)
def test_every_fault_is_injected_detected_and_scored(client, workspace, fault):
    exp = run_fault(client, workspace["orders"]["id"], fault, seed=11)
    assert exp["status"] == "completed"
    truth, evaluation = exp["ground_truth"], exp["evaluation"]
    assert truth["fault_type"] == fault and truth["affected_rows"] > 0
    assert evaluation["detected"] is True, evaluation
    assert evaluation["counts"]["false_positive_signals"] == 0, evaluation["false_positives"]
    assert evaluation["missed_signals"] == []
    assert exp["result_version_id"] and exp["lab_dataset_id"]


def test_same_seed_reproduces_identical_data_and_new_seed_differs(client, workspace):
    first = run_fault(client, workspace["orders"]["id"], "numeric_outliers", seed=5, column="amount")
    second = run_fault(client, workspace["orders"]["id"], "numeric_outliers", seed=5, column="amount")
    other = run_fault(client, workspace["orders"]["id"], "numeric_outliers", seed=6, column="amount")
    assert first["evaluation"]["modified_sha256"] == second["evaluation"]["modified_sha256"]
    assert first["ground_truth"]["examples"] == second["ground_truth"]["examples"]
    assert other["evaluation"]["modified_sha256"] != first["evaluation"]["modified_sha256"]


def test_original_dataset_is_never_modified(client, workspace, settings):
    orders_id = workspace["orders"]["id"]
    before = client.get(f"/api/v1/datasets/{orders_id}/versions").json()
    stored = {p.name: p.read_bytes() for p in settings.storage_dir.iterdir()}
    for fault in ("column_removal", "row_count_reduction", "duplicate_records"):
        run_fault(client, orders_id, fault)
    after = client.get(f"/api/v1/datasets/{orders_id}/versions").json()
    assert before == after
    for name, content in stored.items():
        assert (settings.storage_dir / name).read_bytes() == content
    assert (settings.storage_dir / f"{before[0]['id']}.csv").read_bytes() == sample_bytes("orders_2026_07.csv")


def test_lab_data_is_hidden_and_removed_on_reset(client, workspace):
    exp = run_fault(client, workspace["orders"]["id"], "missing_values", column="amount")
    names = [d["name"] for d in client.get("/api/v1/datasets").json()["items"]]
    assert all("lab" not in n for n in names)
    with_lab = client.get("/api/v1/datasets", params={"include_lab": True}).json()["items"]
    assert any(d["id"] == exp["lab_dataset_id"] for d in with_lab)
    assert all(n["dataset_id"] != exp["lab_dataset_id"] for n in client.get("/api/v1/lineage").json()["nodes"])
    assert client.delete(f"/api/v1/experiments/{exp['id']}").json()["deleted"] is True
    assert client.get(f"/api/v1/datasets/{exp['lab_dataset_id']}").status_code == 404
    assert client.get(f"/api/v1/experiments/{exp['id']}").status_code == 404
    assert client.get(f"/api/v1/datasets/{workspace['orders']['id']}").status_code == 200


def test_regenerate_same_seed_and_new_seed(client, workspace):
    exp = run_fault(client, workspace["orders"]["id"], "unexpected_categories", seed=3, column="status")
    again = client.post(f"/api/v1/experiments/{exp['id']}/regenerate").json()
    assert again["id"] == exp["id"]
    assert again["lab_dataset_id"] != exp["lab_dataset_id"]
    assert again["evaluation"]["modified_sha256"] == exp["evaluation"]["modified_sha256"]
    assert client.get(f"/api/v1/datasets/{exp['lab_dataset_id']}").status_code == 404  # old lab data removed
    reseeded = client.post(f"/api/v1/experiments/{exp['id']}/regenerate", json={"seed": 99}).json()
    assert reseeded["seed"] == 99
    assert reseeded["evaluation"]["modified_sha256"] != exp["evaluation"]["modified_sha256"]


def test_detector_has_no_access_to_ground_truth():
    params = inspect.signature(detector.run_detection).parameters
    assert set(params) == {"base", "cand", "base_profile", "cand_profile", "rules", "settings", "resolver"}


def test_invalid_experiments_are_rejected(client, workspace):
    orders_id = workspace["orders"]["id"]
    bad = [
        {"fault_type": "numeric_outliers", "params": {"column": "status"}},
        {"fault_type": "numeric_outliers", "params": {"column": "nope"}},
        {"fault_type": "numeric_outliers", "params": {"factor": 1.5}},
        {"fault_type": "missing_values", "params": {"fraction": 2}},
        {"fault_type": "missing_values", "params": {"unknown": 1}},
        {"fault_type": "unexpected_categories", "params": {"column": "status", "values": ["placed"]}},
    ]
    for body in bad:
        response = client.post("/api/v1/experiments", json={"dataset_id": orders_id, **body})
        assert response.status_code == 422, body
    assert (
        client.post("/api/v1/experiments", json={"dataset_id": orders_id, "fault_type": "teleport"}).status_code == 422
    )
    customers_id = workspace["customers"]["id"]
    no_fk = client.post("/api/v1/experiments", json={"dataset_id": customers_id, "fault_type": "referential_integrity"})
    assert no_fk.status_code == 422 and "key column" in no_fk.json()["error"]["message"]


def test_fault_catalogue_lists_eligible_columns(client, workspace):
    body = client.get("/api/v1/experiments/fault-types", params={"dataset_id": workspace["orders"]["id"]}).json()
    by_type = {f["fault_type"]: f for f in body["fault_types"]}
    assert len(by_type) == 10
    assert "amount" in by_type["numeric_outliers"]["eligible_columns"]
    assert "order_id" not in by_type["numeric_outliers"]["eligible_columns"]
    assert by_type["referential_integrity"]["eligible_columns"] == ["customer_id"]
    assert set(by_type["timestamp_corruption"]["eligible_columns"]) == {"order_ts", "shipped_ts"}


def test_simulated_impact_uses_declared_lineage(client, workspace):
    orders_asset = workspace["orders"]["asset_id"]
    report = client.post("/api/v1/lineage/assets", json={"name": "revenue report", "kind": "report"}).json()
    client.post("/api/v1/lineage/edges", json={"source_id": orders_asset, "target_id": report["id"]})
    exp = run_fault(client, workspace["orders"]["id"], "duplicate_records")
    impact = exp["evaluation"]["simulated_impact"]
    assert impact["simulated_origin_state"] == "failing"  # the unique rule newly fails
    assert impact["impacted"][0]["name"] == "revenue report"
    assert impact["impacted"][0]["classification"] == "suspected_impact"


def test_listing_experiments(client, workspace):
    run_fault(client, workspace["orders"]["id"], "missing_values")
    run_fault(client, workspace["orders"]["id"], "row_count_reduction")
    listing = client.get("/api/v1/experiments", params={"dataset_id": workspace["orders"]["id"]}).json()
    assert listing["total"] == 2
    assert "detection" not in listing["items"][0]
    assert listing["items"][0]["outcome"] == "detected"


# ---------------------------------------------------------------- evaluation logic


def _signal(category, column=None, severity="medium"):
    return {
        "key": f"{category}:{column or '*'}",
        "category": category,
        "column": column,
        "severity": severity,
        "title": category,
        "source": "statistics",
    }


TRUTH = {
    "scope": "column",
    "affected_columns": ["amount"],
    "expected": {"primary": ["numeric_outlier"], "accepted": ["distribution_shift"]},
}


def test_evaluation_counts_tp_fp_and_missed():
    result = evaluate(
        TRUTH,
        [
            _signal("numeric_outlier", "amount"),
            _signal("distribution_shift", "amount"),
            _signal("null_rate_increase", "status"),
            _signal("null_rate_decrease", "x", "info"),
        ],
    )
    assert result["detected"] is True
    assert result["counts"]["true_positive_signals"] == 2
    assert result["counts"]["false_positive_signals"] == 1  # info signal not scored
    assert result["signal_precision"] == pytest.approx(2 / 3, abs=1e-4)


def test_evaluation_secondary_only_is_partial_and_wrong_column_is_fp():
    partial = evaluate(TRUTH, [_signal("distribution_shift", "amount")])
    assert partial["detected"] is False and partial["outcome"] == "partially_detected"
    assert partial["missed_signals"] == [{"category": "numeric_outlier", "column": "amount"}]
    wrong = evaluate(TRUTH, [_signal("numeric_outlier", "unit_price")])
    assert wrong["outcome"] == "missed" and wrong["counts"]["false_positive_signals"] == 1


def test_dataset_scope_and_healthy_evaluation():
    truth = {
        "scope": "dataset",
        "affected_columns": [],
        "expected": {"primary": ["duplicate_rows"], "accepted": ["uniqueness_lost"]},
    }
    result = evaluate(truth, [_signal("duplicate_rows"), _signal("uniqueness_lost", "order_id")])
    assert result["detected"] and result["counts"]["false_positive_signals"] == 0
    assert evaluate_healthy([_signal("null_rate_decrease", "a", "info")])["alarm"] is False
    assert evaluate_healthy([_signal("distribution_shift", "a", "low")])["false_positive_signals"] == 1
