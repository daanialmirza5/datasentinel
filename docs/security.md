# Security and privacy

DataSentinel is designed to run on your machine with your data staying there. It has **no
authentication**: run it locally or behind your own access control. The public demo configuration
(`DATASENTINEL_DEMO_MODE=true`) is read-only for that reason. No security certification or
penetration test has been performed.

## Data handling

* **No external services.** The application does not call any external API, AI provider, analytics
  or telemetry service. `GET /api/v1/settings` reports `external_services: []`. The browser loads no
  third-party scripts, fonts or CDNs; the Docker image serves the UI with a strict Content Security
  Policy (`default-src 'self'`).
* **Storage.** Each upload is stored once, byte-for-byte, under a server-generated name
  (`ver_<random>.<csv|json|jsonl>`) in `DATASENTINEL_DATA_DIR/storage`. The original file name is kept
  only as display text; it never becomes part of a path. Stored files are never overwritten.
* **Retention.** Your data is kept until you delete it. Deleting a dataset removes its versions, rules,
  results and stored files immediately (and its generated lab data). Fault-lab data is generated, not
  yours, and expires after `DATASENTINEL_EXPERIMENT_RETENTION_HOURS` (24 h by default).
* **Quarantine is non-destructive.** Nothing in the recommendation engine deletes or overwrites data.
* **Integrity.** `POST /api/v1/maintenance/integrity` (Settings → *Verify integrity*) runs SQLite
  `integrity_check` and `foreign_key_check` and re-hashes every stored file against its recorded
  SHA-256, reporting missing, corrupted and orphaned files without changing anything.

## Defences in place

| Threat | Mitigation |
|---|---|
| Oversized uploads / memory exhaustion | Body size enforced while streaming (declared `Content-Length` rejected up front; chunked bodies counted), plus row, column and cell-length limits enforced during parsing |
| Malicious file content | Files are parsed, never executed: stdlib `csv`, `json` with a recursion guard; binary (NUL) content refused; formula-like cells (`=cmd|…`) stay inert text; React escapes all rendered values |
| Path traversal | Storage keys validated against `^[a-z]{2,8}_[0-9a-f]{16}\.(csv|json|jsonl)$` and resolved paths checked to stay in the storage root; static file serving checks `is_relative_to` |
| ReDoS via `pattern` rules | `regex` module with a per-rule time budget; pattern length ≤ 500 |
| Injection | SQLAlchemy ORM with bound parameters everywhere; no raw SQL built from input |
| Mass assignment / unexpected fields | Pydantic models with `extra="forbid"` on every write payload |
| Information leakage | Uniform error envelope; unexpected exceptions return a generic 500 with a request id (details only in server logs) |
| Cross-origin abuse | CORS restricted to configured origins, no credentials |
| Clickjacking / MIME sniffing | `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, `Permissions-Policy` denying camera, microphone and geolocation |
| Public demo misuse | Demo mode refuses uploads and edits (403) |
| Secrets in Git | No secrets are required; `.env` is git-ignored; `.env.example` contains placeholders only. The optional PostgreSQL URL must come from the environment |
| Vulnerable dependencies | All versions pinned; `pip-audit` and `npm audit` run in CI and reported no known vulnerabilities at the time of writing; Dependabot configured |
| Container | Runs as an unprivileged user (uid 10001); data on a volume |

Security tests live in `backend/tests/test_security.py` and `test_ingestion.py`.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
