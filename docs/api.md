# API

Base path: `/api/v1`. Interactive documentation is served by the running API at
`/api/v1/docs` (Swagger UI) and `/api/v1/redoc`; the machine-readable spec is exported to
[`openapi.json`](openapi.json).

## Conventions

* JSON everywhere except the upload (`multipart/form-data`) and report export (Markdown/JSON download).
* **Errors** always have this shape, with an `X-Request-Id` response header that matches `request_id`:

  ```json
  {"error": {"code": "validation_failed", "message": "Request validation failed",
             "details": [{"location": ["query", "limit"], "message": "Input should be greater than or equal to 1"}]},
   "request_id": "3f9c1e0a2b7d4c11"}
  ```

  Codes: `bad_request` 400, `not_found` 404, `conflict` 409, `payload_too_large` 413,
  `unsupported_media_type` 415, `validation_failed` 422, `demo_mode` 403, `internal_error` 500
  (never includes internals).
* **Pagination**: `limit` / `offset` query parameters; responses are `{items, total, limit, offset}`.
* Identifiers are opaque prefixed strings (`ds_…`, `ver_…`, `rule_…`, `exp_…`, `rpt_…`, `asset_…`).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness: database reachable, migrations at head, storage writable (503 otherwise) |
| POST | `/datasets/import` | Upload a file as a new dataset (`dataset_name`) or next version (`dataset_id`) |
| GET | `/datasets` | List (`q`, `kind`, `include_lab`, pagination) |
| GET / PATCH / DELETE | `/datasets/{id}` | Read, rename/describe, delete (removes files) |
| GET | `/datasets/{id}/versions`, `/versions/{vid}`, `/versions/{vid}/summary` | Version history and import summary |
| POST | `/datasets/{id}/versions/{vid}/quarantine`, `/release` | Non-destructive quarantine |
| DELETE | `/datasets/{id}/versions/{vid}` | Delete one version (not the only one) |
| GET | `/datasets/{id}/preview` | Paginated parsed rows (`version_id`, `offset`, `limit`) |
| GET | `/datasets/{id}/rejected-rows` | Rows rejected during import with reasons |
| GET | `/datasets/{id}/profile` | Exact column profile (cached) |
| GET / POST | `/datasets/{id}/rules` | List / create rules |
| GET | `/datasets/{id}/rules/suggestions` | Profile-derived suggestions (nothing is created) |
| GET / PATCH / DELETE | `/rules/{rule_id}` | Read, edit, enable/disable, delete |
| GET | `/rule-types` | Rule catalogue with JSON schemas for parameters |
| POST | `/datasets/{id}/validate` | Run enabled (or listed) rules against a version |
| GET | `/datasets/{id}/validations`, `/validations/{run_id}` | Validation history and details |
| GET | `/datasets/{id}/drift` | Compare versions (`base_version_id`, `candidate_version_id`; defaults: previous → current) |
| GET | `/datasets/{id}/drift/history` | Stored comparison summaries |
| GET | `/datasets/{id}/anomalies` | Within-version outliers, time-series deviations, optional Isolation Forest (`include_ml`) |
| GET | `/lineage` | Assets with health, layout positions, edges and detected cycles |
| POST | `/lineage/assets`, `/lineage/edges` | Declare assets and dependencies (cycles → 409 with path) |
| PATCH / DELETE | `/lineage/assets/{id}`; DELETE `/lineage/edges/{id}` | Edit / remove |
| GET | `/lineage/{asset_id}` | Upstream, downstream, versions, failed rules, schema changes |
| GET | `/lineage/{asset_id}/impact` | Direct/transitive impact, classification, evidence, recommendations |
| GET | `/lineage/impact/summary` | Impact across every failing or anomalous dataset |
| GET | `/experiments/fault-types` | Fault catalogue (+ eligible columns with `dataset_id`) |
| POST / GET | `/experiments` | Run a fault experiment / list |
| GET / DELETE | `/experiments/{id}` | Details / reset (deletes generated data only) |
| POST | `/experiments/{id}/regenerate` | Re-run (same seed → identical data; or `{"seed": n}`) |
| POST / GET | `/reports` | Generate (`dataset_id` or `experiment_id`) / list |
| GET / DELETE | `/reports/{id}` | Read / delete |
| GET | `/reports/{id}/export?format=markdown\|json` | Download |
| GET | `/dashboard` | All dashboard numbers |
| GET | `/settings` | Disclosed configuration (no secrets) |
| GET / POST | `/samples`, `/samples/load` | Sample catalogue / load demo workspace |
| POST | `/maintenance/integrity` | Database check + every stored file against its SHA-256 |
| POST | `/maintenance/retention` | Apply retention now |

## Example session (PowerShell)

```powershell
$api = "http://127.0.0.1:8000/api/v1"
curl.exe -s -F "file=@backend/datasentinel/samples/data/orders_2026_08.csv" -F "dataset_name=orders" "$api/datasets/import"
$ds = (Invoke-RestMethod "$api/datasets?q=orders").items[0].id
curl.exe -s -F "file=@backend/datasentinel/samples/data/orders_2026_09.csv" -F "dataset_id=$ds" "$api/datasets/import" | Out-Null
(Invoke-RestMethod "$api/datasets/$ds/drift").signals | Select-Object severity, title

$rule = @{ name = "currency values"; rule_type = "allowed_values"; column_name = "currency";
           params = @{ values = @("USD", "EUR", "GBP") }; severity = "high" } | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -ContentType "application/json" -Body $rule "$api/datasets/$ds/rules"
$run = Invoke-RestMethod -Method Post -ContentType "application/json" -Body "{}" "$api/datasets/$ds/validate"
$run.results | ForEach-Object { "$($_.rule_name): $($_.status), $($_.violation_count) violations" }   # currency values: failed, 102 violations

# Inject a fault into a copy of the clean August version (v1 of this dataset)
$v1 = (Invoke-RestMethod "$api/datasets/$ds/versions")[0].id
$exp = @{ dataset_id = $ds; version_id = $v1; fault_type = "numeric_outliers"; params = @{ column = "amount" }; seed = 7 } | ConvertTo-Json
(Invoke-RestMethod -Method Post -ContentType "application/json" -Body $exp "$api/experiments").evaluation.outcome   # detected
```
