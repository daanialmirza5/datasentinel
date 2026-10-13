# ADR 0003: SQLite by default, PostgreSQL optional, Alembic migrations

**Status:** accepted · **Date:** 2026-10-13

## Decision
SQLite (WAL, foreign keys on) in the data directory by default; any SQLAlchemy URL via
`DATASENTINEL_DATABASE_URL`, with psycopg for PostgreSQL. Schema changes go through Alembic; the app
migrates on startup, `/ready` reports whether the database is at head, and a test asserts the
migrations match the ORM models. Semi-structured results (profiles, signals) are JSON columns.

## Consequences
+ Zero setup locally; PostgreSQL verified in Docker.
− JSON columns are not queried relationally; reporting across many results would need extraction.