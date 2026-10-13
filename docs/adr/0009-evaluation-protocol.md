# ADR 0009: Evaluate on synthetic ground truth with fresh seed ranges after each change

**Status:** accepted · **Date:** 2026-10-13

## Decision
The benchmark injects the lab's faults (three intensities, 10 replicates) and includes healthy
redraws as controls; the detector never sees ground truth. Development uses seeds < 100. When an
evaluation run leads to a detector change, the next run uses a new, untouched seed range; superseded
runs are kept and explained ([benchmark history](../benchmark.md#evaluation-history-why-the-reported-seeds-start-at-4000)).

## Consequences
+ Reported numbers are not measured on data that shaped the design.
− Synthetic data is cleaner than reality; results are regression evidence, not real-world accuracy.