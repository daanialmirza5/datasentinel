# ADR 0004: Statistical signals require significance and an effect-size floor

**Status:** accepted · **Date:** 2026-10-13

## Context
With thousands of rows, tests flag differences too small to matter; with many columns and tests,
chance alarms accumulate. Alarm fatigue kills observability tools.

## Decision
A signal requires p < 0.001 **and** a practical effect floor (e.g. Δ ≥ 2 pp missing values, KS D ≥ 0.1,
PSI ≥ 0.1). Tests: two-proportion z / Fisher exact, two-sample KS, χ² homogeneity, two-sample rate
comparison for outliers. Samples < 30 are not tested. Identifier columns are excluded from
distribution tests.

## Consequences
+ 0 / 20 false alarms on healthy controls in the reported benchmark run.
− Small real changes are deliberately not signalled; documented as limitations.