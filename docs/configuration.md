# Configuration reference

All settings are environment variables prefixed with `DATASENTINEL_` (or entries in `backend/.env`).
Lists accept comma-separated values or a JSON array. See [`.env.example`](../.env.example).

| Variable | Default | Description |
|---|---|---|
| `DATASENTINEL_ENVIRONMENT` | `development` | `development`, `test` or `production`. Production hides the storage path in `/settings`. |
| `DATASENTINEL_DATA_DIR` | `backend/var` | SQLite database and uploaded files (`storage/`). |
| `DATASENTINEL_DATABASE_URL` | SQLite in `DATA_DIR` | e.g. `postgresql+psycopg://user:password@host:5432/db` (install `requirements-postgres.txt`). Treat as a secret. |
| `DATASENTINEL_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Browser origins allowed to call the API. Not needed when the API serves the frontend itself. |
| `DATASENTINEL_LOG_LEVEL` | `INFO` | Python logging level: `CRITICAL`, `ERROR`, `WARNING`, `INFO` or `DEBUG` (case-insensitive). |
| `DATASENTINEL_MAX_UPLOAD_MB` | `25` | Upload size limit, enforced while the request body streams. |
| `DATASENTINEL_MAX_ROWS` | `200000` | Maximum data rows per file. |
| `DATASENTINEL_MAX_COLUMNS` | `200` | Maximum columns per file. |
| `DATASENTINEL_MAX_CELL_CHARS` | `10000` | Rows with a longer cell are rejected (and reported). |
| `DATASENTINEL_MAX_VERSIONS_PER_DATASET` | `50` | Further imports are refused (409) — nothing is deleted automatically. |
| `DATASENTINEL_PREVIEW_MAX_PAGE_SIZE` | `200` | Largest preview page. |
| `DATASENTINEL_RULE_EXAMPLE_LIMIT` | `5` | Offending rows stored per rule result. |
| `DATASENTINEL_REGEX_TIMEOUT_SECONDS` | `2` | Time budget per `pattern` rule evaluation. |
| `DATASENTINEL_EXPERIMENT_RETENTION_HOURS` | `24` | Generated fault-lab data expires after this many hours (`0` keeps it until reset). |
| `DATASENTINEL_AUTO_MIGRATE` | `true` | Apply Alembic migrations on startup. |
| `DATASENTINEL_LOAD_SAMPLES_ON_STARTUP` | `false` | Load the demo workspace when the database is empty. |
| `DATASENTINEL_DEMO_MODE` | `false` | Read-only public demo: uploads and edits return 403; the fault lab, rule runs and reports still work. |
| `DATASENTINEL_STATIC_DIR` | unset | Serve a built frontend (`frontend/dist`) from the API process (used by the Docker image). |
| `PORT` | `8000` | Docker image only: listening port (hosting platforms set it). |

Frontend (build time):

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | empty (same origin) | Absolute API URL when the frontend is hosted separately. |
| `DATASENTINEL_API_PROXY` | `http://127.0.0.1:8000` | Dev/preview server proxy target for `/api`. |

Detection thresholds (alpha, effect floors) are code constants in
`backend/datasentinel/detection/statistics.py` (`DetectionConfig`) and are shown read-only on the
Settings page.
