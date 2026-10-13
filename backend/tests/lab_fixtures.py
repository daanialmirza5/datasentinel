from __future__ import annotations

from tests.helpers import import_ok, sample_bytes


def orders_workspace(client) -> dict:
    """customers + July orders with a realistic rule set (including a foreign key)."""
    customers = import_ok(client, sample_bytes("customers.csv"), filename="customers.csv")["dataset"]
    orders = import_ok(client, sample_bytes("orders_2026_07.csv"), filename="orders.csv")["dataset"]
    rules = [
        {"name": "order id unique", "rule_type": "unique", "column_name": "order_id", "severity": "high"},
        {
            "name": "customer exists",
            "rule_type": "foreign_key",
            "column_name": "customer_id",
            "severity": "high",
            "params": {"reference_dataset_id": customers["id"], "reference_column": "customer_id"},
        },
        {
            "name": "status values",
            "rule_type": "allowed_values",
            "column_name": "status",
            "severity": "medium",
            "params": {"values": ["placed", "shipped", "delivered", "cancelled", "returned"]},
        },
        {
            "name": "quantity range",
            "rule_type": "range",
            "column_name": "quantity",
            "severity": "medium",
            "params": {"min": 1, "max": 100},
        },
    ]
    for rule in rules:
        response = client.post(f"/api/v1/datasets/{orders['id']}/rules", json=rule)
        assert response.status_code == 201, response.text
    return {"customers": customers, "orders": orders}


def run_fault(client, dataset_id: str, fault_type: str, seed: int = 7, **params) -> dict:
    response = client.post(
        "/api/v1/experiments", json={"dataset_id": dataset_id, "fault_type": fault_type, "params": params, "seed": seed}
    )
    assert response.status_code == 201, response.text
    return response.json()
