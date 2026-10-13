# Windows setup (PowerShell)

Tested on Windows 11 with Python 3.14 and Node.js 22. Python 3.12+ works; no GPU, WSL or Ubuntu is
needed. Disk: about 1.1 GB for both dependency trees.

## Prerequisites

```powershell
py --version        # Python 3.12, 3.13 or 3.14 (python.org installer or the py launcher)
node --version      # Node.js 20.19+ (22 LTS recommended)
git --version
```

## Backend

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt   # optional: Isolation Forest

# Run the API on http://127.0.0.1:8000 (interactive docs at /api/v1/docs)
.\.venv\Scripts\python.exe -m uvicorn datasentinel.main:app --reload --port 8000
```

The SQLite database and uploaded files are created under `backend\var\` on first start; migrations
run automatically. To start with the demo workspace already loaded:

```powershell
$env:DATASENTINEL_LOAD_SAMPLES_ON_STARTUP = "true"
.\.venv\Scripts\python.exe -m uvicorn datasentinel.main:app --port 8000
```

## Frontend

```powershell
cd frontend
npm ci
npm run dev          # http://localhost:5173 — /api is proxied to http://127.0.0.1:8000
```

Point the dev proxy elsewhere with `$env:DATASENTINEL_API_PROXY = "http://127.0.0.1:8011"`.

## Quality gates

```powershell
# backend (from backend\)
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -p no:logging
.\.venv\Scripts\python.exe -m datasentinel.samples.generator --check

# frontend (from frontend\)
npm run lint
npm run typecheck
npm test
npm run build

# browser end-to-end test (starts its own API on :8011 and Vite on :5175 with a throwaway data dir)
npx playwright test          # uses the installed Microsoft Edge on Windows
```

On Linux/macOS (and in CI) Playwright uses its own Chromium: `npx playwright install chromium`.

## Cleanup

```powershell
Remove-Item -Recurse -Force backend\var, backend\var-e2e      # all local data (irreversible)
Remove-Item -Recurse -Force backend\.venv, frontend\node_modules, frontend\dist
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `DLL load failed … An Application Control policy has blocked this file` | **Windows Smart App Control** blocks unsigned native binaries it has no reputation for (it blocked numpy 2.5 and SQLAlchemy 2.1 wheels on the development machine). The pinned versions in `requirements.txt` were chosen because they load under Smart App Control. If you upgrade and hit this, return to the pinned versions; see [ADR 0007](adr/0007-dependency-pinning-under-smart-app-control.md). Prefer pinning over disabling Smart App Control. |
| `uv venv` / `uvx` executables blocked | Same cause: uv's launcher shims are unsigned. Use `py -3 -m venv` as shown above. |
| UI says "Cannot reach the DataSentinel API" | The backend is not running on :8000, or the proxy target is wrong. Check `http://127.0.0.1:8000/api/v1/ready`. |
| `/api/v1/ready` returns 503 with `migrations.ok = false` | Started with `DATASENTINEL_AUTO_MIGRATE=false`; run `python -m alembic upgrade head` in `backend\` or remove the flag. |
| `Port 5173 is already in use` | Another dev server (or a Docker container) uses it. Stop it or run `npx vite --port 5180`. |
| Import fails with 413 | File larger than `DATASENTINEL_MAX_UPLOAD_MB` (default 25). |
| Import fails with 422 "more than N data rows" | Raise `DATASENTINEL_MAX_ROWS` (default 200,000); memory grows roughly linearly. |
| Profile or drift takes long | Expected above ~100k rows on a laptop (see [benchmark scaling](benchmark.md)). |
| `npx playwright test` cannot find a browser | Install Microsoft Edge, or run `$env:PW_CHANNEL="chromium"; npx playwright install chromium`. |
| Settings via `.env` are ignored | `.env` is read from the working directory of the API process (`backend\`). |
