# ADR 0006: Lineage is declared and acyclic; impact is labelled by evidence

**Status:** accepted · **Date:** 2026-10-13

## Decision
Lineage edges are declared by users (datasets become nodes automatically). Edges that would create
a cycle are rejected with the cycle path; traversals remain cycle-safe regardless. Impact labels:
`confirmed_failure` (own failing checks), `suspected_impact` (direct reader of a failing input, or own
anomalies), `unverified_risk` (further downstream, no evidence), `no_known_impact`.

## Consequences
+ No false claims of discovered dependencies or confirmed corruption.
− Users must maintain the lineage graph.