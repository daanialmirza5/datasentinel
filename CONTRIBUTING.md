# Contributing

Thanks for your interest in DataSentinel.

## Development setup

Follow [docs/setup-windows.md](docs/setup-windows.md) (the same commands work on macOS/Linux with
`.venv/bin/python`).

## Before opening a pull request

```powershell
# backend
cd backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -p no:logging
# frontend
cd ..\frontend
npm run lint; npm run typecheck; npm test; npm run build
npx playwright test     # end-to-end
```

CI runs the same checks plus a Docker build and dependency audits.

## Guidelines

* **Keep the core pure.** Detection, rules, lineage and lab code take tables/dicts and return dicts;
  database access belongs in `services/`, HTTP concerns in `api/`.
* **Never report what was not measured.** New detectors must return `not_evaluated` /
  `insufficient_sample` rather than guess, and must include evidence with every signal.
* **Statistical changes need evidence.** Add unit tests (including a healthy-data false-positive
  test) and re-run the benchmark on a *new* seed range; record the run in
  [docs/benchmark.md](docs/benchmark.md).
* **Schema changes need a migration:**
  `.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"` and keep
  `test_migrations_match_models` green.
* **API changes need a fresh spec:** regenerate [docs/openapi.json](docs/openapi.json) from `backend/`
  with `.\.venv\Scripts\python.exe -c "import json,pathlib; from datasentinel.main import create_app; pathlib.Path('../docs/openapi.json').write_text(json.dumps(create_app().openapi(), indent=1) + '\n', encoding='utf-8', newline='\n')"`.
* **Dependencies:** pin exact versions and explain the benefit in the PR. On Windows, check that new
  native wheels load under Smart App Control ([ADR 0007](docs/adr/0007-dependency-pinning-under-smart-app-control.md)).
* Commit messages: imperative mood, one logical change per commit.

## Reporting bugs

Open an issue with steps to reproduce, the request id from the error message (if any), and versions
(`GET /api/v1/health`). Do not attach real or sensitive data — reproduce with synthetic data.
