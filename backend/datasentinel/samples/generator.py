"""Deterministic generator for the bundled sample datasets.

Run ``python -m datasentinel.samples.generator`` to (re)write the files in ``samples/data`` or
``python -m datasentinel.samples.generator --check`` to verify the committed files are reproducible.

The data is synthetic. A small number of quality issues are *deliberately planted* in the
September orders export and in the sensor readings so the demo workspace has something real to
find; they are listed in ``PLANTED_ISSUES`` and in docs/synthetic-data.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED = 20260701

COUNTRIES = ["US", "GB", "DE", "FR", "CA", "IN", "AU", "NL"]
COUNTRY_P = [0.38, 0.12, 0.11, 0.09, 0.09, 0.08, 0.07, 0.06]
STATUSES = ["placed", "shipped", "delivered", "cancelled", "returned"]
STATUS_P = [0.10, 0.20, 0.60, 0.06, 0.04]
CURRENCIES = ["USD", "EUR", "GBP"]
CURRENCY_P = [0.70, 0.20, 0.10]
CATEGORIES = ["Electronics", "Home", "Toys", "Books", "Garden"]

PLANTED_ISSUES = {
    "orders_2026_09.csv": [
        "ship_country null rate raised from ~1.5% to ~18%",
        "unexpected currency category 'JPY' in ~4% of rows",
        "amount multiplied by 100 in ~1.5% of rows (cents/units bug)",
        "~2% of rows duplicated",
        "column 'discount' renamed to 'discount_amount'",
    ],
    "sensor_readings.jsonl": [
        "sensor-b temperature stuck at 85.0 for six hourly readings on 2026-09-17",
    ],
}


def _customers(rng: np.random.Generator, n: int = 600) -> list[dict[str, object]]:
    rows = []
    start = date(2023, 1, 1)
    for i in range(n):
        signup = start + timedelta(days=int(rng.integers(0, 1270)))
        rows.append(
            {
                "customer_id": 1000 + i,
                "email": f"customer{1000 + i}@example.com",
                "country": str(rng.choice(COUNTRIES, p=COUNTRY_P)),
                "segment": "business" if rng.random() < 0.22 else "consumer",
                "signup_date": signup.isoformat(),
                "lifetime_value": round(float(rng.lognormal(5.0, 0.8)), 2),
            }
        )
    return rows


def _orders(
    rng: np.random.Generator, month: int, n: int, first_id: int, *, with_channel: bool, ship_null_p: float = 0.015
) -> list[dict[str, object]]:
    rows = []
    month_start = datetime(2026, month, 1, tzinfo=UTC)
    days_in_month = (datetime(2026, month + 1, 1, tzinfo=UTC) - month_start).days
    for i in range(n):
        ts = month_start + timedelta(seconds=int(rng.integers(0, days_in_month * 86400)))
        quantity = int(min(rng.geometric(0.45), 12))
        unit_price = round(float(rng.lognormal(3.4, 0.55)), 2)
        gross = quantity * unit_price
        discount = 0.0 if rng.random() < 0.7 else round(gross * float(rng.uniform(0.02, 0.15)), 2)
        status = str(rng.choice(STATUSES, p=STATUS_P))
        shipped = ""
        if status in ("shipped", "delivered", "returned"):
            shipped = (ts + timedelta(hours=int(rng.integers(12, 120)))).strftime("%Y-%m-%dT%H:%M:%SZ")
        row: dict[str, object] = {
            "order_id": first_id + i,
            "customer_id": int(rng.integers(1000, 1600)),
            "order_ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "shipped_ts": shipped,
            "status": status,
            "currency": str(rng.choice(CURRENCIES, p=CURRENCY_P)),
            "quantity": quantity,
            "unit_price": f"{unit_price:.2f}",
            "discount": f"{discount:.2f}",
            "amount": f"{gross - discount:.2f}",
            "ship_country": "" if rng.random() < ship_null_p else str(rng.choice(COUNTRIES, p=COUNTRY_P)),
        }
        if with_channel:
            row["channel"] = str(rng.choice(["web", "mobile", "marketplace"], p=[0.55, 0.35, 0.10]))
        rows.append(row)
    return rows


def _plant_september_issues(rng: np.random.Generator, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    for row in rows:
        if rng.random() < 0.18:
            row["ship_country"] = ""
        if rng.random() < 0.04:
            row["currency"] = "JPY"
        if rng.random() < 0.015:
            row["amount"] = f"{float(str(row['amount'])) * 100:.2f}"
        row["discount_amount"] = row.pop("discount")
    duplicate_idx = rng.choice(len(rows), size=int(len(rows) * 0.02), replace=False)
    out = list(rows)
    for idx in sorted(duplicate_idx.tolist()):
        out.insert(int(rng.integers(0, len(out))), dict(rows[idx]))
    return out


def _daily_revenue(orders: list[dict[str, object]]) -> list[dict[str, object]]:
    by_day: dict[str, list[float]] = {}
    for row in orders:
        if row["status"] == "cancelled":
            continue
        day = str(row["order_ts"])[:10]
        by_day.setdefault(day, []).append(float(str(row["amount"])))
    return [
        {
            "date": day,
            "order_count": len(values),
            "revenue": f"{sum(values):.2f}",
            "avg_order_value": f"{sum(values) / len(values):.2f}",
        }
        for day, values in sorted(by_day.items())
    ]


def _products(rng: np.random.Generator, n: int = 150) -> list[dict[str, object]]:
    rows = []
    for i in range(n):
        category = str(rng.choice(CATEGORIES))
        rows.append(
            {
                "product_id": f"P-{i + 1:04d}",
                "name": f"{category} item {i + 1}",
                "category": category,
                "price": round(float(rng.lognormal(3.3, 0.6)), 2),
                "in_stock": bool(rng.random() < 0.85),
                "launched_on": (date(2022, 1, 1) + timedelta(days=int(rng.integers(0, 1500)))).isoformat(),
                "dimensions": {
                    "weight_kg": round(float(rng.uniform(0.1, 12.0)), 2),
                    "fragile": bool(rng.random() < 0.2),
                },
            }
        )
    return rows


def _sensor_readings(rng: np.random.Generator) -> list[dict[str, object]]:
    rows = []
    start = datetime(2026, 9, 1, tzinfo=UTC)
    baselines = {"sensor-a": 21.0, "sensor-b": 23.5, "sensor-c": 19.0}
    stuck = {start + timedelta(days=16, hours=h) for h in range(10, 16)}
    for hour in range(28 * 24):
        ts = start + timedelta(hours=hour)
        for device, base in baselines.items():
            temp = base + 2.5 * np.sin(2 * np.pi * (ts.hour - 9) / 24) + float(rng.normal(0, 0.6))
            if device == "sensor-b" and ts in stuck:
                temp = 85.0
            rows.append(
                {
                    "device_id": device,
                    "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "temperature_c": round(temp, 2),
                    "humidity_pct": round(float(np.clip(rng.normal(45, 6), 5, 95)), 1),
                    "status": "ok" if rng.random() > 0.01 else "warn",
                }
            )
    return rows


def _csv_text(rows: list[dict[str, object]]) -> str:
    buffer = io.StringIO()
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def build_files() -> dict[str, str]:
    """Return {filename: content}. Fully determined by SEED."""
    rng = np.random.default_rng(SEED)
    customers = _customers(rng)
    orders_jul = _orders(rng, 7, 2400, 500_000, with_channel=False)
    orders_aug = _orders(rng, 8, 2550, 510_000, with_channel=True)
    orders_sep = _plant_september_issues(rng, _orders(rng, 9, 2480, 520_000, with_channel=True))
    return {
        "customers.csv": _csv_text(customers),
        "orders_2026_07.csv": _csv_text(orders_jul),
        "orders_2026_08.csv": _csv_text(orders_aug),
        "orders_2026_09.csv": _csv_text(orders_sep),
        "daily_revenue.csv": _csv_text(_daily_revenue(orders_jul)),
        "products.json": json.dumps(_products(rng), indent=1) + "\n",
        "sensor_readings.jsonl": "".join(json.dumps(r) + "\n" for r in _sensor_readings(rng)),
    }


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify committed files instead of writing")
    args = parser.parse_args(argv)
    files = build_files()
    if args.check:
        mismatched = [
            name
            for name, content in files.items()
            if not (DATA_DIR / name).exists()
            or digest((DATA_DIR / name).read_text(encoding="utf-8")) != digest(content)
        ]
        for name in mismatched:
            print(f"MISMATCH {name}")
        print("ok" if not mismatched else f"{len(mismatched)} file(s) differ")
        return 1 if mismatched else 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (DATA_DIR / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {name} sha256={digest(content)[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
