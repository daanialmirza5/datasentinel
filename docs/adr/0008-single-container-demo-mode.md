# ADR 0008: Single container serving API and UI; read-only demo mode for public hosting

**Status:** accepted · **Date:** 2026-10-13

## Decision
The Docker image builds the frontend and serves it from FastAPI (`DATASENTINEL_STATIC_DIR`) with a
strict CSP. For public hosting on a free tier (ephemeral disk, sleeping instances), demo mode loads
the synthetic workspace on start and refuses uploads and edits, while the fault lab and reports work.

## Consequences
+ One service, no CORS, fits Render's free tier.
+ A public URL cannot be used to collect other people's data.
− The public demo cannot show your own data; run locally for that.