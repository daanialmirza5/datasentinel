from __future__ import annotations

from datasentinel.samples.generator import DATA_DIR

ORDERS_CSV = b"order_id,amount,status\n1,10.5,paid\n2,20.0,paid\n3,,refunded\n4,15.25,paid\n"


def upload(client, content: bytes, filename: str = "orders.csv", **form):
    data = {k: v for k, v in form.items() if v is not None}
    return client.post("/api/v1/datasets/import", files={"file": (filename, content, "text/csv")}, data=data)


def import_ok(client, content: bytes, filename: str = "orders.csv", **form) -> dict:
    response = upload(client, content, filename, **form)
    assert response.status_code == 201, response.text
    return response.json()


def sample_bytes(name: str) -> bytes:
    return (DATA_DIR / name).read_bytes()
