# Benchmark results (2026-10-12)

Configuration: `scenarios.json` — 10 replicates × 2500 rows per baseline; evaluation seeds start at 3000.

Environment: datasentinel 0.1.0, python 3.14.7, platform Windows-11-10.0.26300-SP0, processor Intel64 Family 6 Model 142 Stepping 12, GenuineIntel, cpu_count 4, numpy 2.3.3, pandas 2.3.3

## Statistics + declared rules

| Metric | Value |
|---|---|
| Fault scenarios / healthy controls | 280 / 20 |
| Scenario recall (all intensities) | 0.807 |
| Scenario recall (default intensity) | 0.960 |
| Healthy false-positive rate | 0.100 |
| Scenario precision | 0.991 |
| F1 | 0.890 |
| Signal precision | 1.000 |
| Schema drift accuracy | 1.000 |
| Rule violation counts exact | 82 / 82 |
| Detection latency median / p95 (ms, 2500 rows) | 122.4 / 168.4 |

| Fault | Low | Default | High |
|---|---|---|---|
| column_removal | — | 10/10 | — |
| distribution_shift | 6/10 | 7/10 | 10/10 |
| duplicate_records | 0/10 | 10/10 | 10/10 |
| missing_values | 0/10 | 10/10 | 10/10 |
| numeric_outliers | 0/10 | 9/10 | 10/10 |
| referential_integrity | 10/10 | 10/10 | 10/10 |
| row_count_reduction | 0/10 | 10/10 | 10/10 |
| schema_type_change | 10/10 | 10/10 | 10/10 |
| timestamp_corruption | 6/10 | 10/10 | 10/10 |
| unexpected_categories | 8/10 | 10/10 | 10/10 |

Most frequent false-positive signals: `numeric_outlier:amount` ×2

## Statistics only (no rules)

| Metric | Value |
|---|---|
| Fault scenarios / healthy controls | 280 / 20 |
| Scenario recall (all intensities) | 0.650 |
| Scenario recall (default intensity) | 0.860 |
| Healthy false-positive rate | 0.100 |
| Scenario precision | 0.989 |
| F1 | 0.784 |
| Signal precision | 1.000 |
| Schema drift accuracy | 1.000 |
| Detection latency median / p95 (ms, 2500 rows) | 75.1 / 101.1 |

| Fault | Low | Default | High |
|---|---|---|---|
| column_removal | — | 10/10 | — |
| distribution_shift | 6/10 | 7/10 | 10/10 |
| duplicate_records | 0/10 | 10/10 | 10/10 |
| missing_values | 0/10 | 10/10 | 10/10 |
| numeric_outliers | 0/10 | 9/10 | 10/10 |
| referential_integrity | 0/10 | 0/10 | 0/10 |
| row_count_reduction | 0/10 | 10/10 | 10/10 |
| schema_type_change | 10/10 | 10/10 | 10/10 |
| timestamp_corruption | 0/10 | 10/10 | 10/10 |
| unexpected_categories | 0/10 | 10/10 | 10/10 |

Most frequent false-positive signals: `numeric_outlier:amount` ×2

## Impact propagation

6000 / 6000 source nodes on 200 random DAGs (30 nodes) matched the reference downstream set, distances and paths (accuracy 1.0000). Cycle-prevention checks correct: 1.0000.

## Scaling (single run each)

| Rows | CSV MB | Parse+infer s | Profile s | Detection s | Peak Python alloc MB |
|---|---|---|---|---|---|
| 10,000 | 0.8 | 0.484 | 0.099 | 0.185 | 1.7 |
| 100,000 | 8.12 | 4.827 | 1.435 | 1.703 | 15.5 |

Peak allocation is measured with tracemalloc (Python-level allocations during detection only; it excludes memory already held by the loaded tables).
