# Known limitations

Honest boundaries of the current implementation.

## Detection

* **Relative detectors need a clean baseline.** Version comparisons flag *changes*. A defect already
  present in the previous version is not re-flagged as new (e.g. more ×50 errors on top of the
  planted ×100 errors in the September demo export were not detected). Declared rules are the
  remedy: they check absolute expectations on every version.
* **Effect floors are deliberate blind spots.** Missing-value increases under 2 percentage points,
  duplicate increases under 0.5 pp, row-count changes under 20 %, fewer than 5 new-category rows and
  KS shifts with D < 0.1 are not signalled. The benchmark's "low" intensities show this.
* **Independence assumption.** The tests treat rows as independent. Autocorrelated or clustered data
  (sensor streams, sessions) makes p-values optimistic.
* **Zero-inflated, wide-spread columns** (e.g. discounts) hide moderate scaling errors; 3 of 10
  default-intensity outlier faults on `discount` were missed in the benchmark.
* **No seasonality model.** Time-series checks use a robust z-score across days; strongly weekly or
  monthly patterns can produce deviations that are normal for the business.
* **Rename detection is heuristic** and explicitly labelled *possible* / *likely*, never confirmed.
* **Type inference is threshold-based** (95 %). A column that is 90 % numeric is treated as text with
  a `mixed` flag rather than as a number with 10 % invalid values.
* **Benchmarks are synthetic** (one generator family, 20 healthy controls). They are regression
  evidence, not a guarantee of real-world accuracy.

## Product

* **No authentication or multi-user model.** Intended for local use or behind an access proxy.
* **Lineage is declared by hand** (or by the demo loader). Nothing is inferred from SQL, logs or
  orchestrators.
* **File-based ingestion only** (CSV/TSV, JSON, JSON Lines up to the configured limits). No database
  connectors, no streaming, no Parquet.
* **In-process analysis.** Profiling and drift run synchronously in the request; above ~100k rows a
  request takes seconds (see [benchmark scaling](benchmark.md)). There is no job queue.
* **Re-parsing cost.** Versions are stored as original bytes and re-parsed (with a small in-memory
  cache) when needed.
* **Single process.** The table cache is per process; horizontal scaling would need shared storage
  and cache invalidation.
* **Detection thresholds are code constants**, not per-dataset settings.
* **Timezone handling:** timestamps without offsets are interpreted as UTC.
