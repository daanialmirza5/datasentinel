# Benchmark: methodology and results

Every number here was produced by `backend/benchmarks/run_benchmark.py` on the machine described
below and is stored in [`backend/benchmarks/results/latest.json`](../backend/benchmarks/results/latest.json)
(including every per-scenario record). Nothing was edited by hand.

```powershell
cd backend
.\.venv\Scripts\python.exe -m benchmarks.run_benchmark          # ~3 minutes on a 4-core laptop
.\.venv\Scripts\python.exe -m benchmarks.run_benchmark --quick  # smoke run (2 replicates)
```

## Setup

* **Data:** each replicate generates 600 customers and a 2,500-row month of orders with the same
  generator as the sample data (lognormal prices, geometric quantities, categorical status /
  currency / country, ~1.5 % missing ship country, order and ship timestamps).
* **Faults:** the 10 lab faults at three intensities (column removal has one), 10 replicates each →
  **280 fault scenarios** per mode. Target columns are chosen by the seeded injector. Parameters
  are in [`scenarios.json`](../backend/benchmarks/scenarios.json); "low" intensities are deliberately
  near or below the detectors' documented floors to show where detection stops.
* **Healthy controls:** per replicate, an independent redraw of the same month and a redraw of the
  next month with ±10 % volume → **20 controls** per mode. Any actionable signal on a control is a
  false alarm.
* **Modes:** *statistics + declared rules* (a realistic rule set: unique id, foreign key to customers,
  not-null, allowed values, ranges, column comparison, timestamp window, row count) and *statistics
  only* (no rules).
* **Isolation:** the detector receives the two tables, their profiles and the rules — never the ground
  truth. Scoring uses the same `evaluate` function as the in-app lab.

Metric definitions are in the module docstring of `run_benchmark.py`; in short: *scenario recall* =
share of fault scenarios with at least one expected signal on an affected column; *healthy FPR* =
share of controls with any actionable signal; *scenario precision* = detected faults ÷ (detected
faults + alarmed controls); *signal precision* = share of actionable signals in fault scenarios that
match the injected fault's expected or consequential categories on affected columns.

## Results (reported run: seeds 4000–4009)

Environment: Python 3.14.7, numpy 2.3.3, pandas 2.3.3, Windows 11, Intel Core (4 logical CPUs).

| Metric | Statistics + rules | Statistics only |
|---|---|---|
| Fault scenarios / healthy controls | 280 / 20 | 280 / 20 |
| Scenario recall — default intensity | **0.960** | 0.860 |
| Scenario recall — all intensities | 0.786 | 0.650 |
| Healthy false-positive rate | **0.000** (0 / 20) | 0.000 (0 / 20) |
| Scenario precision | 1.000 | 1.000 |
| F1 (all intensities) | 0.880 | 0.788 |
| Signal precision | 1.000 | 1.000 |
| Schema drift accuracy | 1.000 | 1.000 |
| Rule violation counts exactly equal to injected rows | 77 / 77 | — |
| Detection latency, 2,500 rows (median / p95) | 124 ms / 168 ms | 77 ms / 106 ms |

Detected scenarios per fault (statistics + rules; 10 per cell):

| Fault | Low | Default | High | Notes |
|---|---|---|---|---|
| Column removal | — | 10 | — | |
| Schema type change | 10 | 10 | 10 | low = 2 % unit suffixes → reported as invalid values |
| Referential integrity | 10 | 10 | 10 | **0/30 without rules** — needs a declared foreign key |
| Unexpected categories | 3 | 10 | 10 | low = 0.2 % ≈ 5 rows, at the new-category floor |
| Distribution shift | 6 | 9 | 10 | low = 0.1σ; the default miss was a 0.3σ shift of small integers |
| Timestamp corruption | 4 | 10 | 10 | low = 0.2 % ≈ 3–5 rows |
| Numeric outliers | 0 | 7 | 10 | default misses: 50× errors in the zero-inflated `discount` column |
| Missing values | 1 | 10 | 10 | low = +1 pp, below the 2 pp effect floor |
| Duplicate records | 0 | 10 | 10 | low = 0.2 %, below the 0.5 pp floor |
| Row-count reduction | 0 | 10 | 10 | low = −10 %, inside the ±20 % tolerance |

**Impact propagation:** 6,000 / 6,000 source nodes on 200 random DAGs (30 nodes, p = 0.08) matched an
independent shortest-path implementation (`scipy.sparse.csgraph`) on the downstream set, every hop
distance and every returned path; 2,000 / 2,000 cycle-prevention checks were correct.

**Scaling (single run each, same laptop):**

| Rows | CSV size | Parse + infer | Profile | Detection incl. rules | Peak Python allocation during detection |
|---|---|---|---|---|---|
| 10,000 | 0.8 MB | 0.55 s | 0.11 s | 0.19 s | 1.7 MB |
| 100,000 | 8.1 MB | 5.0 s | 1.45 s | 1.7 s | 15.5 MB |

Peak allocation is measured with `tracemalloc` and covers Python-level allocations during detection
only (not the tables already in memory), so it is a lower bound on process memory.

## How to read these numbers

* **0 / 20 false alarms does not mean a 0 % false-positive rate.** With 20 controls the 95 % upper
  bound is about 15 % (rule of three). More controls would tighten this.
* **The data is synthetic and well-behaved.** Real data has seasonality, autocorrelation, mixed
  populations and genuine business change. Expect more signals that are true changes but not
  defects, and treat these results as a regression baseline for the detectors, not a promise.
* **Rules matter.** Referential-integrity faults are invisible to statistics alone; declared
  expectations raised default-intensity recall from 0.86 to 0.96.
* **Low intensities show the floors working as designed:** small changes are deliberately not
  alarmed on.

## Evaluation history (why the reported seeds start at 4000)

Thresholds were set from conventions (alpha = 0.001, KS D ≥ 0.1, PSI ≥ 0.1, …) during development on
seeds < 100 and the sample data. Evaluation runs then exposed weaknesses. Each fix was a
methodological correction, and each subsequent run used a fresh, untouched seed range so the
reported numbers are not measured on data that influenced the design:

| Run | Seeds | Finding | Change |
|---|---|---|---|
| 1 | 1000–1009 ([results](../backend/benchmarks/results/run1-seeds-1000.md)) | Outlier faults missed in zero-inflated `discount`; one false positive from a multi-column rule mis-attributed by the evaluator; injector counted rows whose value (0 × factor) did not change | Hurdle-style fences on non-zero values; rule signals list all inspected columns; injector only targets changeable rows |
| 2 | 2000–2009 ([results](../backend/benchmarks/results/run2-seeds-2000.md)) | Healthy FPR 0.10 (outliers on `amount`, `unit_price`) | Outlier test compared to the baseline rate *as if known*; replaced with a two-sample proportion test |
| 3 | 3000–3009 ([results](../backend/benchmarks/results/run3-seeds-3000.md)) | Healthy FPR still 0.10 — both alarms from one atypical baseline; linear-scale fences sat inside the natural tail of skewed amounts | Log-scale fences for strictly positive, skewed measures (the rule the within-version detector already used) |
| 4 | 4000–4009 | Reported above, as-is | — |

Earlier runs' default-intensity recall (with rules) was 0.94, 0.96 and 0.96; their healthy FPR was
0.00, 0.10 and 0.10.
