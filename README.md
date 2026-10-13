# DataSentinel

**Catch silent data failures before they corrupt your decisions.**

An explainable data observability platform for detecting data quality failures, schema drift,
statistical anomalies, and downstream pipeline impact.

> Work in progress — see `docs/` as features land.

## Layout

- `backend/` — FastAPI service (Python)
- `frontend/` — React + TypeScript + Vite dashboard

## Quick start (Windows PowerShell)

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn datasentinel.main:app --reload

cd ..\frontend
npm ci
npm run dev
```
