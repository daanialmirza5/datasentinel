# Detection methodology

DataSentinel reports **signals**: evidence that something deserves investigation. A signal is not
proof of corruption. Every signal carries a category, an optional column, a severity, a plain-language
explanation and machine-readable evidence (test statistic, p-value, counts, examples).

The design principle for statistical signals: **significance and practical size**. With thousands
of rows a test detects differences far too small to matter, so a signal needs both `p < alpha`
(default 0.001) *and* an effect above a floor. Columns with fewer than 30 non-missing values on
either side are not tested and are reported as `insufficient_sample`.

## Ingestion and type inference

* Every cell is parsed as text; missing-value tokens (`""`, `NA`, `N/A`, `null`, `None`, `NaN`, `-`,
  …) become missing. Rows with the wrong field count, invalid JSON lines or oversized cells are
  *rejected and reported* with their line number, never silently dropped.
* A column gets the most specific type (boolean → integer → float → datetime) that **≥ 95 %** of its
  non-missing values conform to. The rest are counted as *invalid values* (not coerced). Columns
  between 50 % and 95 % numeric are flagged `mixed`.
* `0`/`1` are integers, not booleans. Digits with leading zeros (`00123`) stay text (identifiers).
  Bare integers are never read as epoch timestamps. Ambiguous `dd/mm` vs `mm/dd` dates are flagged.

## Profiling

All statistics are exact (no sampling): counts, missing %, distinct %, uniqueness, min/max,
mean/median, sample standard deviation, quantiles (p01…p99), IQR, string lengths, category
frequencies (≤ 50 distinct), boolean shares, datetime ranges and future/pre-1971 counts. Histograms
are binned summaries of the exact data. Profiles are cached per version and algorithm version.

## Quality rules

Twelve rule types (`column_exists`, `not_null`, `range`, `expected_type`, `pattern`, `unique`,
`allowed_values`, `aggregate_range`, `timestamp_range`, `row_count`, `column_comparison`,
`foreign_key`). Each evaluation returns exactly one of:

| Status | Meaning |
|---|---|
| `passed` | Evaluated over ≥ 1 value; no violation |
| `failed` | ≥ 1 violation (or the dataset-level condition does not hold) |
| `not_evaluated` | Could not be applied: column absent, no non-missing values, reference dataset unavailable, incompatible types. **Never shown as passing.** |
| `error` | Attempted but aborted (invalid regex, regex timeout) |

Regular expressions run with the `regex` module's timeout (default 2 s total per rule) to bound
catastrophic backtracking (ReDoS).

## Version-to-version detectors

| Detector | Method | Signal when |
|---|---|---|
| Added / removed columns | Set difference | Always (removed = high, added = low) |
| Renames | Removed×added pairs scored by value similarity (KS or Jaccard), null-rate similarity and name similarity | score ≥ 0.6 → *possible*, ≥ 0.8 with similar names → *likely*. **Never "confirmed".** |
| Type change | Inferred types differ | numeric/datetime → text is critical |
| Nullability | Previously no missing values, now some | Always (medium) |
| Missing-value rate | Two-proportion z-test; Fisher's exact test when an expected cell < 5 | p < 0.001 and Δ ≥ 2 percentage points |
| Invalid values / unparseable timestamps | Same test on non-conforming share | p < 0.001 and Δ ≥ 0.5 pp |
| Numeric distribution | Two-sample Kolmogorov–Smirnov; PSI over baseline deciles as effect size | p < 0.001 and D ≥ 0.1 |
| Numeric outliers | Count beyond the **baseline's** far-out fences (Q1 − 3·IQR, Q3 + 3·IQR); compare the two versions' rates with the proportion test | p < 0.001 and ≥ 3 excess values |
| New categories | Values absent from the baseline (categorical columns) | ≥ 5 rows and ≥ 0.5 % of rows |
| Category mix | χ² test of homogeneity over baseline categories (sparse cells pooled); PSI | p < 0.001 and PSI ≥ 0.1 |
| Disappeared categories | Baseline categories with ≥ 1 % share absent | Always (low) |
| Uniqueness lost | A column unique in the baseline repeats | Always (high) |
| Row count | Relative change | ≥ 20 % |
| Duplicate rows | Proportion test on exact-duplicate share | p < 0.001 and Δ ≥ 0.5 pp |
| Implausible timestamps | Future (> now + 1 day) or pre-1971 share, proportion test | p < 0.001 and ≥ 3 excess |

**Assumptions and safeguards**

* Rows are treated as independent observations. Heavily autocorrelated data (e.g. per-second
  sensor streams) violates this and makes p-values optimistic.
* KS assumes continuous distributions; on discrete data (small integers) it is conservative —
  it under-reports rather than over-reports.
* **Identifier columns** (names like `id`, `*_id`, `uuid`, `*_key`, or integer/text columns that are
  unique in the baseline) are excluded from distribution and outlier tests: their values are labels,
  and a new month of sequential ids would otherwise "shift".
* Strictly positive, right-skewed measures (sample skewness > 1, e.g. prices and amounts) get their
  outlier fences on the **log scale**; zero-inflated columns (≥ 50 % zeros) are fenced on their
  non-zero values. Both decisions came out of the benchmark (see [benchmark](benchmark.md)).
* The outlier test compares *two estimated rates*; an earlier version treated the baseline rate as
  known and produced false alarms (benchmark run 2).
* About four tests run per column. At alpha = 0.001 the expected number of chance signals per
  comparison is roughly 0.004 × columns before the effect-size floors, which reduce it further.

## Within-version anomalies

* **Robust outliers:** modified z-score |0.6745·(x − median)/MAD| > 3.5 (Iglewicz & Hoaglin), log
  scale for strictly positive skewed columns, Tukey 3×IQR fallback when MAD = 0. If a method would
  flag more than 5 % of a column, the column is reported as *not applicable* — outliers are rare by
  definition, so that distribution (zero-inflated, multi-modal) violates the method's assumption.
* **Time-series deviations:** for the most complete timestamp column spanning ≥ 14 days with a median
  of ≥ 10 rows per day, daily row counts and daily means are scored with the robust z-score across
  days (|z| > 3.5). The first and last day are partial buckets and are not scored. Seasonality is not
  modelled.
* **Isolation Forest (optional):** scikit-learn, fixed seed, robust-scaled numeric columns. Ranks
  unusual rows; scores are not calibrated probabilities. Not used by any headline metric.

## Lineage and impact

Lineage is a declared DAG. Adding an edge that would close a cycle is rejected with the cycle path.
All traversals are BFS with visited sets (cycle-safe even if the database was edited externally);
Tarjan's algorithm (iterative) reports any cycles. Impact follows declared edges only; classification
rules are in [architecture](architecture.md#health-and-impact-semantics).

## Recommendations

Rule-based mapping from evidence to actions, ordered contain → investigate → recover → verify →
prevent. Each recommendation lists its evidence. Quarantine and "restore previous version" are
offered as explicit user actions; nothing is executed or deleted automatically. A previous version
is offered for restore only if its latest validation passed every enabled rule.
