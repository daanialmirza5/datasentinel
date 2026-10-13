# ADR 0001: One FastAPI service and one React SPA

**Status:** accepted · **Date:** 2026-10-13

## Context
The product needs ingestion, statistics, a rules engine, lineage, experiments and reports, on a
laptop with ~8 GB RAM, without paid services. The audience is engineers evaluating the design.

## Decision
A single Python service (FastAPI, SQLAlchemy, pandas/SciPy) and a single-page React app. The domain
core (`ingestion`, `profiling`, `rules`, `detection`, `lineage`, `lab`, `recommendations`) is pure
Python with no I/O; `services/` handles persistence; `api/` handles HTTP.

## Consequences
+ One process to run, debug and deploy; the benchmark calls the same functions as the API.
+ Python's data stack gives exact statistics without extra infrastructure.
− Analysis runs inside requests (no job queue); large files block a worker for seconds.