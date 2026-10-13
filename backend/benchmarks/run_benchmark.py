"""Reproducible evaluation of DataSentinel's detectors against synthetic ground truth.

Usage (from backend/):
    .\\.venv\\Scripts\\python.exe -m benchmarks.run_benchmark            # full evaluation config
    .\\.venv\\Scripts\\python.exe -m benchmarks.run_benchmark --quick    # 2 replicates, no scaling run

Writes benchmarks/results/latest.json and benchmarks/results/latest.md. Every number in those
files is measured by this script; nothing is estimated or copied in by hand.

Metric definitions
------------------
* Scenario recall (per fault and intensity): share of fault scenarios where at least one expected
  (primary) signal was raised for an affected column ("detected").
* Healthy false-positive rate: share of healthy control comparisons (independent redraws from the
  same generator) that raised at least one actionable signal.
* Scenario precision: detected fault scenarios / (detected fault scenarios + alarmed healthy
  controls), with fault and control counts reported because precision depends on their ratio.
* F1: harmonic mean of scenario precision and overall scenario recall.
* Signal precision: true-positive actionable signals / all actionable signals across fault
  scenarios (a signal is a true positive when it matches the fault's expected or consequential
  categories on an affected column; see datasentinel/lab/evaluation.py).
* Schema drift accuracy: share of schema-fault and healthy comparisons whose reported schema changes
  are exactly the injected ones (and none for healthy data).
* Rule violation exactness: for scenarios where a declared rule targets the injected change, the
  share where the rule's violation count equals the number of injected rows exactly.
* Impact propagation correctness: on random DAGs, share of (graph, source) pairs where the
  downstream set and every hop distance match an independent shortest-path implementation
  (scipy.sparse.csgraph) and every returned path is a real edge path of that length.
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path

from datasentinel import __version__
from datasentinel.config import Settings
from datasentinel.detection.pipeline import DEFAULT_CONFIG
from datasentinel.ingestion.parser import ParseLimits, parse_bytes
from datasentinel.lab.detector import run_detection
from datasentinel.lab.evaluation import evaluate, evaluate_healthy
from datasentinel.lab.faults import FaultContext, inject
from datasentinel.lineage.graph import Graph, downstream, would_create_cycle
from datasentinel.models import QualityRule
from datasentinel.profiling import profile_table
from datasentinel.rules.params import PARAM_MODELS
from datasentinel.samples.generator import _csv_text, _customers, _orders
from datasentinel.services.datasets import LoadedTable, build_table

HERE = Path(__file__).resolve().parent
LIMITS = ParseLimits(max_rows=1_000_000, max_columns=500, max_cell_chars=100_000)


def table_from_rows(rows: list[dict[str, object]]) -> LoadedTable:
    return build_table(parse_bytes(_csv_text(rows).encode(), "csv", LIMITS))


def table_from_frame(frame: pd.DataFrame) -> LoadedTable:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n", na_rep="")
    return build_table(parse_bytes(buffer.getvalue().encode(), "csv", LIMITS))


def make_rules() -> list[QualityRule]:
    specs = [
        ("order_id unique", "unique", "order_id", {}, "high"),
        (
            "customer exists",
            "foreign_key",
            "customer_id",
            {"reference_dataset_id": "customers", "reference_column": "customer_id"},
            "high",
        ),
        ("customer_id present", "not_null", "customer_id", {}, "high"),
        (
            "status values",
            "allowed_values",
            "status",
            {"values": ["placed", "shipped", "delivered", "cancelled", "returned"]},
            "medium",
        ),
        ("currency values", "allowed_values", "currency", {"values": ["USD", "EUR", "GBP"]}, "high"),
        ("quantity range", "range", "quantity", {"min": 1, "max": 100}, "medium"),
        ("amount range", "range", "amount", {"min": 0, "max": 10000}, "high"),
        (
            "shipped after ordered",
            "column_comparison",
            "shipped_ts",
            {"operator": "ge", "other_column": "order_ts"},
            "medium",
        ),
        ("order_ts not in future", "timestamp_range", "order_ts", {"max_future_days": 1}, "medium"),
        ("monthly volume", "row_count", None, {"min": 1000}, "medium"),
    ]
    rules = []
    for index, (name, rule_type, column, params, severity) in enumerate(specs):
        parsed = PARAM_MODELS[rule_type].model_validate(params).model_dump(mode="json")
        rules.append(
            QualityRule(
                id=f"rule_bench_{index}",
                name=name,
                rule_type=rule_type,
                column_name=column,
                params=parsed,
                severity=severity,
                enabled=True,
            )
        )
    return rules


RULE_TARGETS = {
    # fault -> {column: rule_id} where a declared rule directly measures the injected rows
    "unexpected_categories": {"status": "rule_bench_3", "currency": "rule_bench_4"},
    "referential_integrity": {"customer_id": "rule_bench_1"},
    "duplicate_records": {None: "rule_bench_0"},
    "missing_values": {"customer_id": "rule_bench_2"},
}


class World:
    """One replicate: customers + a baseline month of orders, all from one seed."""

    def __init__(self, seed: int, rows: int) -> None:
        rng = np.random.default_rng(seed)
        self.seed = seed
        self.rows = rows
        self.customers = table_from_rows(_customers(rng))
        self.base = table_from_rows(_orders(rng, 7, rows, 500_000, with_channel=False))
        self.base_profile = profile_table(self.base)

    def resolver(self, dataset_id: str) -> LoadedTable | None:
        return self.customers if dataset_id == "customers" else None


def detect(world: World, cand: LoadedTable, rules: list[QualityRule], settings: Settings) -> tuple[dict, float]:
    started = time.perf_counter()
    cand_profile = profile_table(cand)
    result = run_detection(world.base, cand, world.base_profile, cand_profile, rules, settings, world.resolver)
    return result, (time.perf_counter() - started) * 1000


def expected_schema(truth: dict[str, Any]) -> list[tuple[str, str]]:
    if truth["fault_type"] == "column_removal":
        return [("removed", truth["affected_columns"][0])]
    if truth["fault_type"] == "schema_type_change" and truth["params"]["fraction"] > 0.05:
        return [("type_change", truth["affected_columns"][0])]
    return []


def run_scenarios(config: dict[str, Any], settings: Settings, replicates: int) -> dict[str, Any]:
    rules_all = make_rules()
    modes = {"with_rules": rules_all, "statistics_only": []}
    records: list[dict[str, Any]] = []
    healthy: list[dict[str, Any]] = []
    for r in range(replicates):
        seed = config["base_seed"] + r
        world = World(seed, config["rows"])
        for fault in config["faults"]:
            for intensity, params in fault["intensities"].items():
                fault_seed = seed * 100 + len(records) % 97
                ctx = FaultContext(world.base, world.base_profile, np.random.default_rng(fault_seed), ["customer_id"])
                modified, truth = inject(fault["fault_type"], ctx, dict(params))
                cand = table_from_frame(modified)
                for mode, rules in modes.items():
                    detection, ms = detect(world, cand, rules, settings)
                    ev = evaluate(truth, detection["signals"])
                    reported_schema = sorted((c["change_type"], c["column"]) for c in detection["schema_changes"])
                    rule_check = None
                    target = RULE_TARGETS.get(fault["fault_type"], {})
                    column = truth["affected_columns"][0] if truth["affected_columns"] else None
                    if mode == "with_rules" and column in target:
                        result = next(
                            x for x in detection["rule_results"]["candidate"] if x["rule_id"] == target[column]
                        )
                        rule_check = {
                            "expected": truth["affected_rows"],
                            "reported": result["violation_count"],
                            "exact": result["violation_count"] == truth["affected_rows"],
                        }
                    records.append(
                        {
                            "replicate": r,
                            "seed": seed,
                            "fault_seed": fault_seed,
                            "fault_type": fault["fault_type"],
                            "intensity": intensity,
                            "mode": mode,
                            "params": truth["params"],
                            "detected": ev["detected"],
                            "outcome": ev["outcome"],
                            "tp_signals": ev["counts"]["true_positive_signals"],
                            "fp_signals": ev["counts"]["false_positive_signals"],
                            "fp_examples": [f"{s['category']}:{s['column']}" for s in ev["false_positives"]],
                            "schema_correct": reported_schema == sorted(expected_schema(truth)),
                            "schema_relevant": fault["fault_type"] in ("column_removal", "schema_type_change"),
                            "rule_check": rule_check,
                            "detection_ms": ms,
                        }
                    )
        rng = np.random.default_rng(seed + 50_000)
        controls = {
            "same_month_redraw": _orders(rng, 7, config["rows"], 600_000, with_channel=False),
            "next_month_redraw": _orders(
                rng, 8, int(config["rows"] * rng.uniform(0.9, 1.1)), 700_000, with_channel=False
            ),
        }
        for kind in config["healthy_controls"]:
            cand = table_from_rows(controls[kind])
            for mode, rules in modes.items():
                detection, ms = detect(world, cand, rules, settings)
                ev = evaluate_healthy(detection["signals"])
                healthy.append(
                    {
                        "replicate": r,
                        "kind": kind,
                        "mode": mode,
                        "alarm": ev["alarm"],
                        "fp_signals": ev["false_positive_signals"],
                        "fp_examples": [f"{s['category']}:{s['column']}" for s in ev["false_positives"]],
                        "schema_correct": detection["schema_changes"] == [],
                        "detection_ms": ms,
                    }
                )
        print(f"  replicate {r + 1}/{replicates} done", flush=True)
    return {"records": records, "healthy": healthy}


def summarize(records: list[dict[str, Any]], healthy: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for mode in ("with_rules", "statistics_only"):
        recs = [r for r in records if r["mode"] == mode]
        ctrl = [h for h in healthy if h["mode"] == mode]
        by_fault: dict[str, dict[str, Any]] = defaultdict(dict)
        for fault in sorted({r["fault_type"] for r in recs}):
            for intensity in ("low", "default", "high"):
                subset = [r for r in recs if r["fault_type"] == fault and r["intensity"] == intensity]
                if subset:
                    by_fault[fault][intensity] = {
                        "scenarios": len(subset),
                        "detected": sum(r["detected"] for r in subset),
                        "recall": round(sum(r["detected"] for r in subset) / len(subset), 4),
                        "false_positive_signals": sum(r["fp_signals"] for r in subset),
                    }
        detected = sum(r["detected"] for r in recs)
        alarms = sum(h["alarm"] for h in ctrl)
        recall = detected / len(recs) if recs else 0.0
        precision = detected / (detected + alarms) if detected + alarms else 0.0
        tp_sig = sum(r["tp_signals"] for r in recs)
        fp_sig = sum(r["fp_signals"] for r in recs)
        default_recs = [r for r in recs if r["intensity"] == "default"]
        schema = [r["schema_correct"] for r in recs if r["schema_relevant"]] + [h["schema_correct"] for h in ctrl]
        rule_checks = [r["rule_check"] for r in recs if r["rule_check"]]
        fp_counter: dict[str, int] = defaultdict(int)
        for item in [*recs, *ctrl]:
            for example in item["fp_examples"]:
                fp_counter[example] += 1
        out[mode] = {
            "fault_scenarios": len(recs),
            "healthy_controls": len(ctrl),
            "scenario_recall_all_intensities": round(recall, 4),
            "scenario_recall_default_intensity": round(sum(r["detected"] for r in default_recs) / len(default_recs), 4)
            if default_recs
            else None,
            "healthy_false_positive_rate": round(alarms / len(ctrl), 4) if ctrl else None,
            "scenario_precision": round(precision, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "signal_precision": round(tp_sig / (tp_sig + fp_sig), 4) if tp_sig + fp_sig else None,
            "schema_drift_accuracy": round(sum(schema) / len(schema), 4) if schema else None,
            "rule_violation_exactness": {"checked": len(rule_checks), "exact": sum(c["exact"] for c in rule_checks)}
            if rule_checks
            else None,
            "by_fault": by_fault,
            "most_common_false_positives": sorted(fp_counter.items(), key=lambda kv: -kv[1])[:10],
            "detection_ms": {
                "median": round(statistics.median([r["detection_ms"] for r in recs]), 1),
                "p95": round(float(np.percentile([r["detection_ms"] for r in recs], 95)), 1),
            },
        }
    return out


def lineage_benchmark(cfg: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(cfg["seed"])
    n, p = cfg["nodes"], cfg["edge_probability"]
    pairs = exact = 0
    cycle_checks = cycle_correct = 0
    started = time.perf_counter()
    for _ in range(cfg["graphs"]):
        adjacency = np.triu(rng.random((n, n)) < p, k=1)  # i -> j only for i < j: a DAG
        graph = Graph()
        for i in range(n):
            graph.add_node(str(i), name=str(i), kind="dataset")
        for i, j in zip(*np.nonzero(adjacency), strict=True):
            graph.add_edge(str(i), str(j))
        reference = shortest_path(csr_matrix(adjacency.astype(float)), directed=True, unweighted=True)
        for source in range(n):
            pairs += 1
            ours = downstream(graph, str(source))
            expected = {
                str(j): int(reference[source, j]) for j in range(n) if j != source and np.isfinite(reference[source, j])
            }
            ok = {k: v["distance"] for k, v in ours.items()} == expected
            for target, info in ours.items():
                path = [int(x) for x in info["path"]]
                ok &= path[0] == source and path[-1] == int(target) and len(path) == info["distance"] + 1
                ok &= all(adjacency[a, b] for a, b in itertools.pairwise(path))
            exact += ok
        for _ in range(10):
            a, b = (int(x) for x in rng.integers(0, n, 2))
            cycle = would_create_cycle(graph, str(a), str(b))
            reachable = a == b or np.isfinite(reference[b, a])
            cycle_checks += 1
            cycle_correct += (cycle is not None) == bool(reachable)
    return {
        "graphs": cfg["graphs"],
        "nodes": n,
        "source_nodes_checked": pairs,
        "exact_matches": exact,
        "accuracy": round(exact / pairs, 4),
        "cycle_checks": cycle_checks,
        "cycle_check_accuracy": round(cycle_correct / cycle_checks, 4),
        "seconds": round(time.perf_counter() - started, 2),
    }


def scaling_benchmark(rows_list: list[int], settings: Settings) -> list[dict[str, Any]]:
    results = []
    rules = make_rules()
    for rows in rows_list:
        rng = np.random.default_rng(77)
        customers = table_from_rows(_customers(rng))
        base_rows = _orders(rng, 7, rows, 1, with_channel=False)
        cand_rows = _orders(rng, 7, rows, 2_000_000, with_channel=False)
        csv_bytes = _csv_text(base_rows).encode()
        t0 = time.perf_counter()
        base = build_table(parse_bytes(csv_bytes, "csv", LIMITS))
        t1 = time.perf_counter()
        base_profile = profile_table(base)
        t2 = time.perf_counter()
        cand = table_from_rows(cand_rows)
        cand_profile = profile_table(cand)
        t3 = time.perf_counter()
        run_detection(
            base,
            cand,
            base_profile,
            cand_profile,
            rules,
            settings,
            lambda ds, ref=customers: ref if ds == "customers" else None,
        )
        t4 = time.perf_counter()
        tracemalloc.start()
        run_detection(
            base,
            cand,
            base_profile,
            cand_profile,
            rules,
            settings,
            lambda ds, ref=customers: ref if ds == "customers" else None,
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results.append(
            {
                "rows": rows,
                "file_mb": round(len(csv_bytes) / 1024 / 1024, 2),
                "parse_and_infer_s": round(t1 - t0, 3),
                "profile_s": round(t2 - t1, 3),
                "detection_incl_rules_s": round(t4 - t3, 3),
                "detection_peak_python_alloc_mb": round(peak / 1024 / 1024, 1),
            }
        )
        print(f"  scaling {rows} rows done", flush=True)
    return results


def environment() -> dict[str, Any]:
    return {
        "datasentinel": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Benchmark results ({result['generated_at'][:10]})",
        "",
        f"Configuration: `{result['config_file']}` — {result['replicates']} replicates × "
        f"{result['rows']} rows per baseline; evaluation seeds start at {result['base_seed']}.",
        "",
        "Environment: " + ", ".join(f"{k} {v}" for k, v in result["environment"].items()),
        "",
    ]
    for mode, label in (
        ("with_rules", "Statistics + declared rules"),
        ("statistics_only", "Statistics only (no rules)"),
    ):
        s = result["summary"][mode]
        lines += [
            f"## {label}",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Fault scenarios / healthy controls | {s['fault_scenarios']} / {s['healthy_controls']} |",
            f"| Scenario recall (all intensities) | {s['scenario_recall_all_intensities']:.3f} |",
            f"| Scenario recall (default intensity) | {s['scenario_recall_default_intensity']:.3f} |",
            f"| Healthy false-positive rate | {s['healthy_false_positive_rate']:.3f} |",
            f"| Scenario precision | {s['scenario_precision']:.3f} |",
            f"| F1 | {s['f1']:.3f} |",
            f"| Signal precision | {s['signal_precision']:.3f} |",
            f"| Schema drift accuracy | {s['schema_drift_accuracy']:.3f} |",
        ]
        if s["rule_violation_exactness"]:
            r = s["rule_violation_exactness"]
            lines.append(f"| Rule violation counts exact | {r['exact']} / {r['checked']} |")
        lines += [
            f"| Detection latency median / p95 (ms, {result['rows']} rows) | {s['detection_ms']['median']} / "
            f"{s['detection_ms']['p95']} |",
            "",
            "| Fault | Low | Default | High |",
            "|---|---|---|---|",
        ]
        for fault, by in s["by_fault"].items():
            cells = [
                f"{by[i]['detected']}/{by[i]['scenarios']}" if i in by else "—" for i in ("low", "default", "high")
            ]
            lines.append(f"| {fault} | " + " | ".join(cells) + " |")
        if s["most_common_false_positives"]:
            lines += [
                "",
                "Most frequent false-positive signals: "
                + ", ".join(f"`{k}` ×{v}" for k, v in s["most_common_false_positives"]),
            ]
        lines.append("")
    lin = result["lineage"]
    lines += [
        "## Impact propagation",
        "",
        f"{lin['exact_matches']} / {lin['source_nodes_checked']} source nodes on {lin['graphs']} random DAGs "
        f"({lin['nodes']} nodes) matched the reference downstream set, distances and paths "
        f"(accuracy {lin['accuracy']:.4f}). Cycle-prevention checks correct: {lin['cycle_check_accuracy']:.4f}.",
        "",
    ]
    if result["scaling"]:
        lines += [
            "## Scaling (single run each)",
            "",
            "| Rows | CSV MB | Parse+infer s | Profile s | Detection s | Peak Python alloc MB |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {s['rows']:,} | {s['file_mb']} | {s['parse_and_infer_s']} | {s['profile_s']} | "
            f"{s['detection_incl_rules_s']} | {s['detection_peak_python_alloc_mb']} |"
            for s in result["scaling"]
        ]
        lines += [
            "",
            "Peak allocation is measured with tracemalloc (Python-level allocations during detection only; "
            "it excludes memory already held by the loaded tables).",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DataSentinel evaluation benchmark.")
    parser.add_argument("--config", default=str(HERE / "scenarios.json"))
    parser.add_argument("--quick", action="store_true", help="2 replicates and no scaling run (smoke test)")
    parser.add_argument("--out", default=str(HERE / "results"))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    replicates = 2 if args.quick else config["replicates"]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp), environment="test")
        print(f"Running {replicates} replicate(s)…", flush=True)
        scenarios = run_scenarios(config, settings, replicates)
        lineage = lineage_benchmark(config["lineage"])
        scaling = [] if args.quick else scaling_benchmark(config["scaling_rows"], settings)
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config_file": Path(args.config).name,
        "replicates": replicates,
        "rows": config["rows"],
        "base_seed": config["base_seed"],
        "detection_config": DEFAULT_CONFIG.as_dict(),
        "environment": environment(),
        "summary": summarize(scenarios["records"], scenarios["healthy"]),
        "lineage": lineage,
        "scaling": scaling,
        "runtime_seconds": round(time.perf_counter() - started, 1),
        "records": scenarios["records"],
        "healthy": scenarios["healthy"],
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = "quick" if args.quick else "latest"
    (out / f"{name}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    (out / f"{name}.md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))
    print(f"Finished in {result['runtime_seconds']} s → {out / (name + '.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
