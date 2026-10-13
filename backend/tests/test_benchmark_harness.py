"""Smoke tests for the benchmark harness (small configurations; the real run is benchmarks/run_benchmark.py)."""

from benchmarks.run_benchmark import lineage_benchmark, run_scenarios, summarize

TINY = {
    "base_seed": 1000,
    "rows": 600,
    "healthy_controls": ["same_month_redraw"],
    "faults": [
        {"fault_type": "unexpected_categories", "intensities": {"default": {"fraction": 0.05}}},
        {"fault_type": "column_removal", "intensities": {"default": {}}},
    ],
}


def test_scenarios_produce_scored_records(settings):
    result = run_scenarios(TINY, settings, replicates=1)
    assert len(result["records"]) == 4 and len(result["healthy"]) == 2
    summary = summarize(result["records"], result["healthy"])
    assert summary["with_rules"]["scenario_recall_all_intensities"] == 1.0
    assert summary["with_rules"]["schema_drift_accuracy"] == 1.0


def test_lineage_benchmark_matches_reference():
    result = lineage_benchmark({"graphs": 5, "nodes": 12, "edge_probability": 0.2, "seed": 1})
    assert result["accuracy"] == 1.0 and result["cycle_check_accuracy"] == 1.0
