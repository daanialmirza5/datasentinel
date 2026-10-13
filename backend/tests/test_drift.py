import numpy as np
import pandas as pd
import pytest

from datasentinel.detection.pipeline import detect_changes
from datasentinel.detection.statistics import proportion_test
from datasentinel.ingestion.parser import ParseLimits, parse_bytes
from datasentinel.profiling import profile_table
from datasentinel.services.datasets import build_table
from tests.helpers import ORDERS_CSV, import_ok, sample_bytes


def load(frame: pd.DataFrame):
    table = build_table(parse_bytes(frame.to_csv(index=False).encode(), "csv", ParseLimits()))
    return table, profile_table(table)


def drift(base: pd.DataFrame, cand: pd.DataFrame) -> dict:
    tb, pb = load(base)
    tc, pc = load(cand)
    return detect_changes(tb, tc, pb, pc)


def keys(result: dict) -> set[tuple[str, str | None]]:
    return {(s["category"], s["column"]) for s in result["signals"]}


def frame(seed: int, n: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "order_id": np.arange(n) + seed * 100_000,
            "amount": np.round(rng.lognormal(3.5, 0.5, n), 2),
            "quantity": rng.integers(1, 6, n),
            "status": rng.choice(["paid", "shipped", "refunded"], n, p=[0.6, 0.3, 0.1]),
            "country": np.where(rng.random(n) < 0.02, None, rng.choice(["US", "DE", "FR"], n)),
            "created": pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(rng.integers(0, 30 * 86400, n), unit="s"),
        }
    )


def test_healthy_redraw_produces_no_signals():
    """Independent draws from the same process must not alarm (false-positive guard)."""
    for seed in range(1, 6):
        result = drift(frame(seed), frame(seed + 50))
        assert result["signals"] == [], (seed, result["signals"])


def test_identifier_columns_are_not_distribution_tested():
    result = drift(frame(1), frame(2))
    order_id = next(c for c in result["column_comparisons"] if c["column"] == "order_id")
    assert order_id["identifier"] is True
    assert order_id["distribution"]["status"] == "skipped_identifier"


def test_added_removed_and_type_changes():
    base = frame(1)
    cand = frame(2).drop(columns=["quantity"])
    cand["coupon"] = "X"
    cand["amount"] = cand["amount"].map(lambda v: f"{v} USD")
    result = drift(base, cand)
    changes = {(c["change_type"], c["column"]) for c in result["schema_changes"]}
    assert ("removed", "quantity") in changes
    assert ("added", "coupon") in changes
    assert ("type_change", "amount") in changes
    type_change = next(s for s in result["signals"] if s["category"] == "type_change")
    assert type_change["severity"] == "critical"
    assert type_change["evidence"]["from"] == "float" and type_change["evidence"]["to"] == "string"


def test_rename_is_reported_as_likely_never_confirmed():
    base = frame(1)
    cand = frame(2).rename(columns={"amount": "amount_usd"})
    result = drift(base, cand)
    rename = next(c for c in result["schema_changes"] if c["change_type"].endswith("_rename"))
    assert rename["from"] == "amount" and rename["to"] == "amount_usd"
    assert rename["change_type"] == "likely_rename"
    assert "not a confirmed" in rename["explanation"]
    assert all(c["change_type"] != "confirmed_rename" for c in result["schema_changes"])


def test_unrelated_add_and_remove_is_not_called_a_rename():
    base = frame(1)
    cand = frame(2).drop(columns=["amount"])
    cand["notes"] = [f"note {i}" for i in range(len(cand))]
    result = drift(base, cand)
    assert not any(c["change_type"].endswith("_rename") for c in result["schema_changes"])


def test_null_rate_increase_and_nullability_change():
    base = frame(1)
    cand = frame(2)
    cand.loc[cand.sample(frac=0.15, random_state=0).index, "amount"] = None
    result = drift(base, cand)
    assert ("null_rate_increase", "amount") in keys(result)
    assert ("nullability_change", "amount") in keys(result)
    evidence = next(s for s in result["signals"] if s["category"] == "null_rate_increase")["evidence"]
    assert evidence["p_value"] < 0.001 and evidence["delta_pp"] == pytest.approx(15.0, abs=0.1)


def test_distribution_shift_detected_and_small_shift_ignored():
    base, cand = frame(1), frame(2)
    cand["amount"] = cand["amount"] * 1.6
    assert ("distribution_shift", "amount") in keys(drift(base, cand))
    tiny = frame(2)
    tiny["amount"] = tiny["amount"] * 1.01
    assert ("distribution_shift", "amount") not in keys(drift(base, tiny))


def test_outliers_relative_to_baseline_tails():
    base, cand = frame(1), frame(2)
    idx = cand.sample(n=40, random_state=1).index
    cand.loc[idx, "amount"] = cand.loc[idx, "amount"] * 100
    result = drift(base, cand)
    assert ("numeric_outlier", "amount") in keys(result)
    signal = next(s for s in result["signals"] if s["category"] == "numeric_outlier")
    assert signal["evidence"]["candidate_count"] >= 40
    assert len(signal["evidence"]["examples"]) == 5


def test_new_category_and_frequency_shift():
    base, cand = frame(1), frame(2)
    cand.loc[cand.sample(frac=0.05, random_state=2).index, "status"] = "chargeback"
    result = drift(base, cand)
    signal = next(s for s in result["signals"] if s["category"] == "new_category")
    assert signal["evidence"]["new_values"] == {"chargeback": 100}
    mix = frame(2)
    mix["status"] = np.random.default_rng(3).choice(["paid", "shipped", "refunded"], len(mix), p=[0.3, 0.3, 0.4])
    assert ("category_frequency_shift", "status") in keys(drift(base, mix))


def test_row_count_drop_and_duplicates():
    base = frame(1)
    assert ("row_count_change", None) in keys(drift(base, frame(2).head(1200)))
    cand = frame(2)
    cand = pd.concat([cand, cand.sample(n=100, random_state=0)], ignore_index=True)
    result = drift(base, cand)
    assert ("duplicate_rows", None) in keys(result)
    assert ("uniqueness_lost", "order_id") in keys(result)


def test_timestamp_corruption():
    base, cand = frame(1), frame(2)
    cand["created"] = cand["created"].astype(str)
    idx = cand.sample(n=40, random_state=0).index
    cand.loc[idx[:20], "created"] = "not-a-date"
    cand.loc[idx[20:], "created"] = "2099-01-01T00:00:00+00:00"
    result = drift(base, cand)
    assert ("timestamp_invalid", "created") in keys(result)
    assert ("timestamp_out_of_range", "created") in keys(result)


def test_small_samples_are_not_tested():
    base, cand = frame(1, n=20), frame(2, n=20)
    cand["amount"] = cand["amount"] * 10
    result = drift(base, cand)
    amount = next(c for c in result["column_comparisons"] if c["column"] == "amount")
    assert amount["distribution"] == {"status": "insufficient_sample"}
    assert not any(s["category"] == "distribution_shift" for s in result["signals"])


def test_proportion_test_uses_fisher_for_sparse_counts():
    p, test = proportion_test(0, 100, 3, 100)
    assert test == "fisher_exact" and 0 < p < 1
    assert proportion_test(0, 100, 0, 100) == (1.0, "none")


def test_sample_orders_v2_to_v3_find_the_planted_issues(client):
    first = import_ok(client, sample_bytes("orders_2026_08.csv"), filename="orders.csv", dataset_name="orders")
    ds_id = first["dataset"]["id"]
    assert client.get(f"/api/v1/datasets/{ds_id}/drift").json()["status"] == "no_baseline"
    import_ok(client, sample_bytes("orders_2026_09.csv"), filename="orders.csv", dataset_id=ds_id)
    body = client.get(f"/api/v1/datasets/{ds_id}/drift").json()
    assert body["status"] == "ok"
    assert body["base"]["version_number"] == 1 and body["candidate"]["version_number"] == 2
    found = {(s["category"], s["column"]) for s in body["signals"]}
    assert {
        ("null_rate_increase", "ship_country"),
        ("new_category", "currency"),
        ("numeric_outlier", "amount"),
        ("duplicate_rows", None),
        ("column_removed", "discount"),
    } <= found
    history = client.get(f"/api/v1/datasets/{ds_id}/drift/history").json()
    assert len(history) == 1 and history[0]["summary"]["signal_count"] == len(body["signals"])


def test_drift_between_explicit_versions_and_errors(client):
    first = import_ok(client, ORDERS_CSV, dataset_name="orders")
    ds_id, v1 = first["dataset"]["id"], first["version"]["id"]
    v2 = import_ok(client, ORDERS_CSV + b"5,1.0,paid\n", dataset_id=ds_id)["version"]["id"]
    body = client.get(f"/api/v1/datasets/{ds_id}/drift", params={"base_version_id": v2, "candidate_version_id": v1})
    assert body.status_code == 200 and body.json()["base"]["id"] == v2
    same = client.get(f"/api/v1/datasets/{ds_id}/drift", params={"base_version_id": v1, "candidate_version_id": v1})
    assert same.status_code == 422


def test_outliers_in_zero_inflated_columns_use_nonzero_fences():
    rng = np.random.default_rng(9)

    def discounts(seed_rng):
        values = np.round(seed_rng.uniform(1, 20, 2000), 2)
        values[seed_rng.random(2000) < 0.7] = 0.0
        return values

    base = pd.DataFrame({"discount": discounts(rng)})
    healthy = pd.DataFrame({"discount": discounts(rng)})
    assert ("numeric_outlier", "discount") not in keys(drift(base, healthy))
    faulty = pd.DataFrame({"discount": discounts(rng)})
    nonzero = faulty.index[faulty["discount"] > 0][:40]
    faulty.loc[nonzero, "discount"] *= 50
    result = drift(base, faulty)
    assert ("numeric_outlier", "discount") in keys(result)
    signal = next(s for s in result["signals"] if s["category"] == "numeric_outlier")
    assert signal["evidence"]["zero_inflated"] is True
