# ADR 0002: Store original upload bytes and re-parse on demand

**Status:** accepted · **Date:** 2026-10-13

## Context
Versions must keep provenance, be comparable later, and never be overwritten. Options: store the
original file, or convert to a columnar format (Parquet via pyarrow, ~70 MB dependency).

## Decision
Store the exact uploaded bytes under a server-generated key with their SHA-256; re-parse with the
same deterministic parser when needed, behind a small in-process LRU cache. Profiles and drift
results are cached in the database.

## Consequences
+ Exact provenance (hash of what the user uploaded), no conversion loss, no pyarrow.
+ Integrity can be verified by re-hashing.
− Re-parsing cost after cache eviction (~0.5 s per 10k rows on the dev laptop).