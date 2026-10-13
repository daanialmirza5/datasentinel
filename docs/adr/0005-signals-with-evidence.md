# ADR 0005: One signal model with evidence; four honest rule statuses

**Status:** accepted · **Date:** 2026-10-13

## Decision
Schema drift, statistics, time series and rules all emit the same `Signal` (category, column,
severity, explanation, evidence). Rules return `passed`, `failed`, `error` or `not_evaluated`; a rule
that could not run is never shown as passing. Health distinguishes deterministic failures
(`failing`) from statistical ones (`anomalous`).

## Consequences
+ The UI, reports, impact analysis and lab evaluation share one vocabulary.
+ Every claim can be traced to numbers.