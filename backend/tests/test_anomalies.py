import importlib.util

import numpy as np
import pandas as pd
import pytest

from datasentinel.detection.anomalies import detect_within_version, isolation_forest, numeric_outliers
from datasentinel.ingestion.parser import ParseLimits, parse_bytes
from datasentinel.profiling import profile_table
from datasentinel.services.datasets import build_table
from tests.helpers import import_ok, sample_bytes

HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


def load(frame: pd.DataFrame):
    table = build_table(parse_bytes(frame.to_csv(index=False).encode(), "csv", ParseLimits()))
    return table, profile_table(table)


def test_mad_outliers_with_examples_sorted_by_score():
    values = [10.0 + (i % 5) * 0.5 for i in range(100)] + [250.0, -90.0]
    table, profile = load(pd.DataFrame({"x": values}))
    [result], _ = numeric_outliers(table, profile)
    assert result["count"] == 2
    assert result["method"].startswith("modified_z")
    assert [e["row"] for e in result["examples"]] == [101, 102]


def test_constant_and_tiny_columns_are_skipped():
    table, profile = load(pd.DataFrame({"constant": [5] * 50, "tiny": [1, 2, 3, 400] + [None] * 46}))
    assert numeric_outliers(table, profile)[0] == []


def test_mad_zero_falls_back_to_iqr():
    values = [1.0] * 60 + [2.0] * 40 + [50.0]
    table, profile = load(pd.DataFrame({"x": values}))
    [result], _ = numeric_outliers(table, profile)
    assert result["method"].startswith("tukey") and result["count"] == 1


def test_skewed_positive_data_uses_log_scale_and_flags_scaling_errors():
    rng = np.random.default_rng(3)
    amounts = np.round(rng.lognormal(3.5, 0.6, 2000), 2)
    amounts[:10] *= 100  # cents-vs-units bug
    table, profile = load(pd.DataFrame({"amount": amounts}))
    [result], skipped = numeric_outliers(table, profile)
    assert "log scale" in result["method"] and not skipped
    assert result["count"] >= 10 and result["pct"] < 2
    assert {e["row"] for e in result["examples"]} <= set(range(1, 11))


def test_zero_inflated_columns_are_not_applicable_rather_than_noisy():
    rng = np.random.default_rng(4)
    discounts = np.where(rng.random(2000) < 0.7, 0.0, np.round(rng.uniform(1, 30, 2000), 2))
    table, profile = load(pd.DataFrame({"discount": discounts}))
    outliers, skipped = numeric_outliers(table, profile)
    assert outliers == []
    assert skipped[0]["column"] == "discount" and skipped[0]["flagged_pct"] > 5


def test_identifier_columns_excluded():
    table, profile = load(pd.DataFrame({"order_id": [*range(100), 10**9]}))
    assert numeric_outliers(table, profile)[0] == []


def test_time_series_requires_enough_days():
    rng = np.random.default_rng(0)
    short = pd.DataFrame(
        {"ts": pd.date_range("2026-01-01", periods=10 * 24, freq="h", tz="UTC"), "v": rng.normal(size=240)}
    )
    table, profile = load(short)
    assert detect_within_version(table, profile)["time_series"] is None


def test_sparse_daily_data_is_not_scored():
    table = build_table(parse_bytes(sample_bytes("customers.csv"), "csv", ParseLimits()))
    ts = detect_within_version(table, profile_table(table))["time_series"]
    assert ts["deviations"] == [] and "rows per day" in ts["skipped"]


def test_sensor_sample_finds_the_stuck_sensor_day():
    table = build_table(parse_bytes(sample_bytes("sensor_readings.jsonl"), "jsonl", ParseLimits()))
    result = detect_within_version(table, profile_table(table))
    ts = result["time_series"]
    assert ts["column"] == "ts" and ts["days"] == 28
    flagged = {(d["date"], d["metric"]) for d in ts["deviations"]}
    assert ("2026-09-17", "mean(temperature_c)") in flagged
    outlier = next(o for o in result["outliers"] if o["column"] == "temperature_c")
    assert all(e["value"] == "85.0" for e in outlier["examples"])
    assert any(s["category"] == "time_series_deviation" for s in result["signals"])


@pytest.mark.ml
@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_isolation_forest_is_deterministic_and_ranks_injected_row_first():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({"a": rng.normal(size=300), "b": rng.normal(size=300)})
    frame.loc[150, ["a", "b"]] = [12.0, -12.0]
    table, profile = load(frame)
    first = isolation_forest(table, profile, seed=7)
    second = isolation_forest(table, profile, seed=7)
    assert first == second
    assert first["ran"] and first["top_rows"][0]["row"] == 151


def test_anomalies_endpoint(client):
    body = import_ok(client, sample_bytes("sensor_readings.jsonl"), filename="sensors.jsonl")
    response = client.get(f"/api/v1/datasets/{body['dataset']['id']}/anomalies", params={"include_ml": HAS_SKLEARN})
    assert response.status_code == 200
    result = response.json()
    assert result["version"]["version_number"] == 1
    assert result["time_series"]["deviations"]
    if HAS_SKLEARN:
        assert result["ml"]["ran"] is True
