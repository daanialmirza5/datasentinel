import math
import statistics

import numpy as np
import pandas as pd
import pytest

from datasentinel.ingestion.parser import ParseLimits, parse_bytes
from datasentinel.profiling import mad_outlier_mask, profile_table
from datasentinel.services.datasets import build_table
from tests.helpers import ORDERS_CSV, import_ok


def profile_of(content: bytes, fmt: str = "csv") -> dict:
    return profile_table(build_table(parse_bytes(content, fmt, ParseLimits())))


def col(profile: dict, name: str) -> dict:
    return next(c for c in profile["columns"] if c["name"] == name)


def test_numeric_statistics_match_reference_implementations():
    values = [3.5, 1.0, 7.25, 2.0, 9.0, 4.5, 6.0, 8.0, 5.5, 10.0]
    content = ("x\n" + "\n".join(str(v) for v in values) + "\n").encode()
    x = col(profile_of(content), "x")
    assert x["type"] == "float"
    assert x["min"] == 1.0 and x["max"] == 10.0
    assert x["mean"] == pytest.approx(statistics.fmean(values))
    assert x["median"] == pytest.approx(statistics.median(values))
    assert x["std"] == pytest.approx(statistics.stdev(values))
    assert x["quantiles"]["p25"] == pytest.approx(float(np.quantile(values, 0.25)))
    assert x["sum"] == pytest.approx(sum(values))


def test_missing_values_distinct_and_duplicates():
    profile = profile_of(b"id,city\n1,Paris\n2,\n3,Paris\n3,Paris\n4,NA\n")
    city = col(profile, "city")
    assert city["null_count"] == 2
    assert city["null_pct"] == pytest.approx(40.0)
    assert city["distinct_count"] == 1
    assert city["is_constant"] is True
    assert profile["duplicate_rows"] == 1
    ids = col(profile, "id")
    assert ids["unique"] is False and ids["duplicate_value_count"] == 1
    assert profile["missing_cells"] == 2


def test_empty_and_constant_columns_are_safe():
    profile = profile_of(b"a,b,c\n,1,x\n,1,x\n,1,x\n")
    a, b = col(profile, "a"), col(profile, "b")
    assert a["type"] == "empty" and a["null_pct"] == 100.0 and "mean" not in a
    assert b["std"] == 0.0
    assert b["outliers"]["mad_count"] is None  # zero spread -> not meaningful
    assert b["histogram"]["kind"] == "discrete"


def test_single_row_dataset():
    x = col(profile_of(b"x\n5\n"), "x")
    assert x["std"] is None and x["mean"] == 5.0
    assert x["outliers"]["iqr_count"] is None


def test_categorical_frequencies_and_string_lengths():
    rows = ["status"] + ["paid"] * 60 + ["refunded"] * 30 + ["void"] * 10
    status = col(profile_of(("\n".join(rows) + "\n").encode()), "status")
    assert status["is_categorical"] is True
    assert [c["value"] for c in status["categories"]] == ["paid", "refunded", "void"]
    assert status["categories"][0]["pct"] == pytest.approx(60.0)
    assert status["length"] == {"min": 4, "max": 8, "mean": pytest.approx(5.2)}


def test_datetime_range_and_invalid_values():
    rows = ["ts"] + [f"2026-01-{d:02d}T00:00:00Z" for d in range(1, 29)] + ["2099-01-01", "not-a-date"]
    ts = col(profile_of(("\n".join(rows) + "\n").encode()), "ts")
    assert ts["type"] == "datetime"
    assert ts["min"].startswith("2026-01-01")
    assert ts["max"].startswith("2099-01-01")
    assert ts["future_count"] == 1
    assert ts["invalid_count"] == 1 and ts["invalid_examples"] == ["not-a-date"]


def test_boolean_profile():
    flag = col(profile_of(b"flag\ntrue\nfalse\ntrue\n\n"), "flag")
    assert flag["true_count"] == 2 and flag["false_count"] == 1


def test_mixed_column_reports_numeric_share():
    rows = ["v"] + [str(i) for i in range(80)] + ["unknown"] * 20
    v = col(profile_of(("\n".join(rows) + "\n").encode()), "v")
    assert v["type"] == "string" and v["mixed"] is True


def test_mad_outlier_mask_flags_extremes_only():
    values = np.array([10, 11, 9, 10, 12, 10, 11, 9, 10, 500], dtype=float)
    mask = mad_outlier_mask(values)
    assert mask is not None and mask.tolist() == [False] * 9 + [True]
    assert mad_outlier_mask(np.array([1.0, 2.0])) is None


def test_profile_is_json_safe_with_nan_inputs():
    profile = profile_of(b"x\n1\n2\nnan\n")
    for column in profile["columns"]:
        for value in column.values():
            if isinstance(value, float):
                assert not math.isnan(value)


def test_profile_endpoint_is_cached(client):
    body = import_ok(client, ORDERS_CSV, dataset_name="orders")
    first = client.get(f"/api/v1/datasets/{body['dataset']['id']}/profile").json()
    assert first["cached"] is True  # computed during import
    amount = next(c for c in first["profile"]["columns"] if c["name"] == "amount")
    assert amount["null_count"] == 1
    assert amount["mean"] == pytest.approx((10.5 + 20.0 + 15.25) / 3)


def test_profile_performance_reasonable_for_100k_rows():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {"a": rng.normal(size=100_000), "b": rng.integers(0, 50, 100_000), "c": rng.choice(["x", "y", "z"], 100_000)}
    )
    content = frame.to_csv(index=False).encode()
    import time

    start = time.perf_counter()
    profile = profile_of(content)
    elapsed = time.perf_counter() - start
    assert profile["row_count"] == 100_000
    assert elapsed < 30  # generous bound for slow CI machines; actual timing is in the benchmark
