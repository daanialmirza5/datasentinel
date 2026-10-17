import pytest

from datasentinel.ingestion.parser import ParseLimits, parse_bytes
from datasentinel.rules.engine import EvalContext, RuleSpec, evaluate
from datasentinel.services.datasets import build_table
from tests.helpers import ORDERS_CSV, import_ok

ORDERS = (
    b"order_id,customer_id,amount,status,email,created,shipped,discount\n"
    b"1,10,25.0,paid,a@x.com,2026-01-01T10:00:00Z,2026-01-02T10:00:00Z,0\n"
    b"2,11,-5.0,paid,bad-email,2026-01-02T10:00:00Z,2026-01-01T09:00:00Z,1\n"
    b"3,12,,refunded,c@x.com,2026-01-03T10:00:00Z,,0\n"
    b"3,99,1000000,lost,d@x.com,2099-01-01T00:00:00Z,2099-01-02T00:00:00Z,2\n"
    b"5,10,abc,paid,e@x.com,not-a-date,,0\n"
)
CUSTOMERS = b"customer_id,name\n10,A\n11,B\n12,C\n"


def table(content=ORDERS):
    return build_table(parse_bytes(content, "csv", ParseLimits()))


def run(rule_type, column=None, ctx_table=None, **params):
    ctx = EvalContext(
        table=ctx_table or table(), resolve_reference=lambda ds: table(CUSTOMERS) if ds == "customers" else None
    )
    return evaluate(RuleSpec(rule_type, column, params), ctx)


def test_column_exists():
    assert run("column_exists", "amount").status == "passed"
    missing = run("column_exists", "nope")
    assert missing.status == "failed" and missing.violation_count == 1


def test_missing_column_is_not_evaluated_not_passed():
    outcome = run("not_null", "nope")
    assert outcome.status == "not_evaluated"
    assert "not present" in outcome.message


def test_not_null_with_threshold():
    strict = run("not_null", "amount")
    assert strict.status == "failed"
    assert (strict.violation_count, strict.evaluated_count) == (1, 5)
    assert strict.examples[0]["row"] == 3
    assert run("not_null", "amount", max_null_pct=25).status == "passed"


def test_range_counts_out_of_range_and_non_numeric():
    outcome = run("range", "amount", min=0, max=10000)
    assert outcome.status == "failed"
    assert outcome.evaluated_count == 4  # null excluded
    assert outcome.violation_count == 3  # -5, 1e6, 'abc'
    assert outcome.details == {"non_numeric": 1, "out_of_range": 2}
    assert outcome.violation_pct == pytest.approx(75.0)


def test_expected_type():
    assert run("expected_type", "customer_id", type="integer").status == "passed"
    assert run("expected_type", "customer_id", type="float").status == "passed"  # widening allowed
    mismatch = run("expected_type", "status", type="float")
    assert mismatch.status == "failed" and mismatch.violation_count == 5


def test_pattern_and_invalid_or_catastrophic_regex():
    outcome = run("pattern", "email", regex=r"[^@\s]+@[^@\s]+\.[a-z]+")
    assert outcome.status == "failed" and outcome.violation_count == 1
    assert outcome.examples == [{"row": 2, "values": {"email": "bad-email"}}]
    assert run("pattern", "email", regex="(unclosed").status == "error"
    evil = table(b"v\n" + b"a" * 5000 + b"!\n")
    ctx = EvalContext(table=evil, regex_timeout_seconds=0.2)
    slow = evaluate(RuleSpec("pattern", "v", {"regex": r"(a|aa)+$"}), ctx)
    assert slow.status == "error" and "exceeded" in slow.message


def test_unique_single_and_composite():
    single = run("unique", "order_id")
    assert single.status == "failed" and single.violation_count == 1
    assert run("unique", "order_id", extra_columns=["customer_id"]).status == "passed"


def test_allowed_values_reports_unexpected_values():
    outcome = run("allowed_values", "status", values=["paid", "refunded"])
    assert outcome.violation_count == 1
    assert outcome.details["unexpected_values"] == {"lost": 1}
    assert run("allowed_values", "status", values=["PAID", "REFUNDED", "LOST"], case_sensitive=False).status == "passed"


def test_aggregate_range():
    assert run("aggregate_range", "discount", aggregate="mean", max=1).status == "passed"
    failed = run("aggregate_range", "discount", aggregate="max", max=1)
    assert failed.status == "failed" and failed.details["value"] == 2
    assert run("aggregate_range", "amount", aggregate="null_pct", max=10).status == "failed"


def test_timestamp_range_flags_unparseable_and_future():
    outcome = run("timestamp_range", "created", max_future_days=1)
    assert outcome.violation_count == 2  # 2099 and 'not-a-date'
    assert outcome.details["unparseable"] == 1
    bounded = run("timestamp_range", "created", min="2026-01-02T00:00:00Z", max="2030-01-01T00:00:00Z")
    assert bounded.violation_count == 3


def test_row_count():
    assert run("row_count", min=5, max=5).status == "passed"
    assert run("row_count", min=6).status == "failed"


def test_column_comparison_numeric_and_datetime():
    dates = run("column_comparison", "shipped", operator="ge", other_column="created")
    assert dates.evaluated_count == 3 and dates.violation_count == 1
    assert dates.examples[0]["row"] == 2
    incompatible = run("column_comparison", "status", operator="eq", other_column="amount")
    assert incompatible.status == "not_evaluated"


def test_foreign_key():
    outcome = run("foreign_key", "customer_id", reference_dataset_id="customers", reference_column="customer_id")
    assert outcome.status == "failed" and outcome.violation_count == 1
    assert outcome.details["orphan_values"] == {"99": 1}
    unavailable = run("foreign_key", "customer_id", reference_dataset_id="gone", reference_column="customer_id")
    assert unavailable.status == "not_evaluated"


def test_all_null_column_is_not_evaluated():
    t = table(b"a,b\n1,\n2,\n")
    assert run("range", "b", ctx_table=t, min=0).status == "not_evaluated"
    assert run("pattern", "b", ctx_table=t, regex="x").status == "not_evaluated"


def test_invalid_params_produce_error_status():
    assert run("range", "amount").status == "error"


# ---------------------------------------------------------------- API


def test_rule_crud_and_validation_run(client):
    ds = import_ok(client, ORDERS_CSV, dataset_name="orders")["dataset"]
    base = f"/api/v1/datasets/{ds['id']}"
    created = client.post(
        f"{base}/rules",
        json={"name": "amount present", "rule_type": "not_null", "column_name": "amount", "severity": "high"},
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["params"] == {"max_null_pct": 0.0}
    client.post(
        f"{base}/rules",
        json={
            "name": "status set",
            "rule_type": "allowed_values",
            "column_name": "status",
            "params": {"values": ["paid", "refunded"]},
        },
    )

    run_body = client.post(f"{base}/validate").json()
    assert run_body["summary"]["total"] == 2
    assert run_body["summary"]["failed"] == 1 and run_body["summary"]["passed"] == 1
    assert run_body["summary"]["health"] == "failing"
    failing = next(r for r in run_body["results"] if r["status"] == "failed")
    assert failing["recommendation"]
    assert failing["examples"][0]["row"] == 3

    patched = client.patch(f"/api/v1/rules/{rule['id']}", json={"enabled": False}).json()
    assert patched["enabled"] is False
    rerun = client.post(f"{base}/validate").json()
    assert rerun["summary"]["total"] == 1 and rerun["summary"]["health"] == "passing"

    history = client.get(f"{base}/validations").json()
    assert len(history) == 2
    assert client.get(f"/api/v1/validations/{history[0]['id']}").json()["results"]
    assert client.delete(f"/api/v1/rules/{rule['id']}").json()["deleted"] is True
    assert client.get(f"/api/v1/rules/{rule['id']}").status_code == 404


def test_rules_run_automatically_on_new_versions(client):
    ds = import_ok(client, ORDERS_CSV, dataset_name="orders")["dataset"]
    client.post(
        f"/api/v1/datasets/{ds['id']}/rules", json={"name": "rows", "rule_type": "row_count", "params": {"min": 5}}
    )
    import_ok(client, ORDERS_CSV + b"5,1.0,paid\n", dataset_id=ds["id"])
    runs = client.get(f"/api/v1/datasets/{ds['id']}/validations").json()
    assert runs[0]["trigger"] == "import" and runs[0]["summary"]["passed"] == 1


def test_rule_validation_errors(client):
    ds = import_ok(client, ORDERS_CSV, dataset_name="orders")["dataset"]
    url = f"/api/v1/datasets/{ds['id']}/rules"
    assert (
        client.post(url, json={"name": "x", "rule_type": "range", "column_name": "amount", "params": {}}).status_code
        == 422
    )
    assert client.post(url, json={"name": "x", "rule_type": "not_null"}).status_code == 422
    assert client.post(url, json={"name": "x", "rule_type": "teleport", "column_name": "a"}).status_code == 422
    assert (
        client.post(
            url,
            json={
                "name": "x",
                "rule_type": "foreign_key",
                "column_name": "amount",
                "params": {"reference_dataset_id": "ds_nope", "reference_column": "id"},
            },
        ).status_code
        == 422
    )
    assert client.post(f"/api/v1/datasets/{ds['id']}/validate", json={"rule_ids": ["rule_unknown"]}).status_code == 422


def test_rule_types_catalogue_and_suggestions(client):
    catalogue = client.get("/api/v1/rule-types").json()
    assert len(catalogue["types"]) == 12
    assert all("params_schema" in t for t in catalogue["types"])
    ds = import_ok(client, ORDERS_CSV, dataset_name="orders")["dataset"]
    suggestions = client.get(f"/api/v1/datasets/{ds['id']}/rules/suggestions").json()["suggestions"]
    kinds = {(s["rule_type"], s["column_name"]) for s in suggestions}
    assert ("column_exists", "order_id") in kinds
    for suggestion in suggestions:
        payload = {k: suggestion[k] for k in ("name", "rule_type", "column_name", "params", "severity")}
        assert client.post(f"/api/v1/datasets/{ds['id']}/rules", json=payload).status_code == 201


def test_timestamp_range_rejects_inverted_bounds():
    from pydantic import ValidationError

    from datasentinel.rules.params import TimestampRangeParams

    with pytest.raises(ValidationError, match="min must not exceed max"):
        TimestampRangeParams(min="2026-02-01T00:00:00", max="2026-01-01T00:00:00")
    with pytest.raises(ValidationError, match="timezone"):
        TimestampRangeParams(min="2026-01-01T00:00:00Z", max="2026-02-01T00:00:00")
