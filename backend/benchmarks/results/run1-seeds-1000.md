# Benchmark results (2026-10-12)

Configuration: `scenarios.json` — 10 replicates × 2500 rows per baseline; evaluation seeds start at 1000.

Environment: datasentinel 0.1.0, python 3.14.7, platform Windows-11-10.0.26300-SP0, processor Intel64 Family 6 Model 142 Stepping 12, GenuineIntel, cpu_count 4, numpy 2.3.3, pandas 2.3.3

## Statistics + declared rules

| Metric | Value |
|---|---|
| Fault scenarios / healthy controls | 280 / 20 |
| Scenario recall (all intensities) | 0.779 |
| Scenario recall (default intensity) | 0.940 |
| Healthy false-positive rate | 0.000 |
| Scenario precision | 1.000 |
| F1 | 0.875 |
| Signal precision | 1.000 |
| Schema drift accuracy | 1.000 |
| Rule violation counts exact | 81 / 81 |
| Detection latency median / p95 (ms, 2500 rows) | 123.2 / 166.8 |

| Fault | Low | Default | High |
|---|---|---|---|
| column_removal | — | 10/10 | — |
| distribution_shift | 5/10 | 8/10 | 10/10 |
| duplicate_records | 0/10 | 10/10 | 10/10 |
| missing_values | 3/10 | 10/10 | 10/10 |
| numeric_outliers | 0/10 | 6/10 | 6/10 |
| referential_integrity | 10/10 | 10/10 | 10/10 |
| row_count_reduction | 0/10 | 10/10 | 10/10 |
| schema_type_change | 10/10 | 10/10 | 10/10 |
| timestamp_corruption | 4/10 | 10/10 | 10/10 |
| unexpected_categories | 6/10 | 10/10 | 10/10 |

## Statistics only (no rules)

| Metric | Value |
|---|---|
| Fault scenarios / healthy controls | 280 / 20 |
| Scenario recall (all intensities) | 0.625 |
| Scenario recall (default intensity) | 0.840 |
| Healthy false-positive rate | 0.000 |
| Scenario precision | 1.000 |
| F1 | 0.769 |
| Signal precision | 1.000 |
| Schema drift accuracy | 1.000 |
| Detection latency median / p95 (ms, 2500 rows) | 75.5 / 110.0 |

| Fault | Low | Default | High |
|---|---|---|---|
| column_removal | — | 10/10 | — |
| distribution_shift | 5/10 | 8/10 | 10/10 |
| duplicate_records | 0/10 | 10/10 | 10/10 |
| missing_values | 0/10 | 10/10 | 10/10 |
| numeric_outliers | 0/10 | 6/10 | 6/10 |
| referential_integrity | 0/10 | 0/10 | 0/10 |
| row_count_reduction | 0/10 | 10/10 | 10/10 |
| schema_type_change | 10/10 | 10/10 | 10/10 |
| timestamp_corruption | 0/10 | 10/10 | 10/10 |
| unexpected_categories | 0/10 | 10/10 | 10/10 |

## Impact propagation

6000 / 6000 source nodes on 200 random DAGs (30 nodes) matched the reference downstream set, distances and paths (accuracy 1.0000). Cycle-prevention checks correct: 1.0000.

## Scaling (single run each)

| Rows | CSV MB | Parse+infer s | Profile s | Detection s | Peak Python alloc MB |
|---|---|---|---|---|---|
| 10,000 | 0.8 | 0.591 | 0.11 | 0.195 | 1.7 |
| 100,000 | 8.12 | 5.064 | 1.453 | 1.76 | 15.5 |

Peak allocation is measured with tracemalloc (Python-level allocations during detection only; it excludes memory already held by the loaded tables).
