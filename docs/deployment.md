# Deployment

## 1. Local (native)

See [setup-windows.md](setup-windows.md). Frontend on http://localhost:5173, API on
http://127.0.0.1:8000.

## 2. Local (Docker)

One image builds the frontend and serves it from the API process (no separate web server, no CORS).

```powershell
docker compose up --build                       # http://localhost:8000, demo workspace preloaded
$env:DATASENTINEL_PORT = "8090"; docker compose up --build   # if port 8000 is taken
docker compose down                             # stop (data kept in the datasentinel-data volume)
docker compose down -v                          # stop and delete the data volume
```

With PostgreSQL instead of SQLite:

```powershell
$env:DATASENTINEL_DATABASE_URL = "postgresql+psycopg://datasentinel:datasentinel-local@postgres:5432/datasentinel"
docker compose --profile postgres up --build
```

The compose password is for local use only; set `POSTGRES_PASSWORD` and the URL from a secret store
anywhere else. Image size with the `ml postgres` extras: about 750 MB (build arg `EXTRAS=""` omits
scikit-learn and psycopg).

**Verified locally (2026-10-13):** image built; the container reached `ready` on PostgreSQL 16 with
migrations at head; demo workspace loaded (5 datasets); upload, fault experiment, report export and
the integrity check succeeded over HTTP; all pages loaded in Microsoft Edge under the CSP with no
console errors; demo mode returned 403 for uploads.

## 3. Public demo on Render (prepared, not deployed)

[`render.yaml`](../render.yaml) defines a Blueprint for Render's free web service:

* Docker runtime, health check `/api/v1/ready`.
* `DATASENTINEL_DEMO_MODE=true` (uploads and edits disabled) and the demo workspace loaded on start.
* Free-tier constraints (checked October 2026): 512 MB RAM and 0.1 CPU, sleeps after ~15 idle
  minutes with a cold start of about a minute, ephemeral filesystem, 750 instance-hours per month.
  The design accepts these: the demo is re-seeded on every start and nothing user-supplied is kept.

Steps (requires your Render account — not performed by the author of these files):

1. Push the repository to GitHub.
2. Render dashboard → **New → Blueprint** → select the repository → **Apply**.
3. If the service URL differs from `https://datasentinel-demo.onrender.com`, update
   `DATASENTINEL_CORS_ORIGINS` (only needed if you also host the frontend elsewhere).
4. Verify: `https://<service>.onrender.com/api/v1/ready` returns `"status": "ready"`, then walk the
   [demo script](demo-script.md) in a browser.

Other hosts: any container platform that sets `$PORT` works with the same image. As of October 2026
Fly.io and Koyeb no longer offer a permanent free tier and Railway provides trial credit only, so
those require a paid plan.

## 4. Frontend on static hosting (optional)

Build with the API's public URL and host `frontend/dist` on any static host (GitHub Pages, Netlify,
Cloudflare Pages). Configure the host to serve `index.html` for unknown paths (SPA fallback) and add
the static origin to the API's `DATASENTINEL_CORS_ORIGINS`.

```powershell
cd frontend
$env:VITE_API_BASE_URL = "https://<your-api-host>"
npm run build
```

## Production checklist

* Put authentication in front of the service (reverse proxy / identity-aware proxy) — DataSentinel
  has none.
* Use PostgreSQL and back up both the database and `DATASENTINEL_DATA_DIR/storage` together.
* Set `DATASENTINEL_ENVIRONMENT=production`, explicit `DATASENTINEL_CORS_ORIGINS`, and limits suited
  to your instance size (profiling memory grows linearly with rows × columns).
* Run `POST /api/v1/maintenance/integrity` after restores.
