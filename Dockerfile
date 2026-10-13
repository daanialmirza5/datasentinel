# syntax=docker/dockerfile:1
# Single image: builds the React frontend, then serves it and the API from one FastAPI process.

FROM node:22.23-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
# Optional extras: "ml" (scikit-learn Isolation Forest) and/or "postgres" (psycopg driver).
ARG EXTRAS="ml"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATASENTINEL_DATA_DIR=/data \
    DATASENTINEL_STATIC_DIR=/app/static \
    DATASENTINEL_ENVIRONMENT=production \
    PORT=8000
WORKDIR /app
COPY backend/requirements.txt backend/requirements-ml.txt backend/requirements-postgres.txt ./
RUN pip install -r requirements.txt \
    && if echo "$EXTRAS" | grep -q ml; then pip install -r requirements-ml.txt; fi \
    && if echo "$EXTRAS" | grep -q postgres; then pip install -r requirements-postgres.txt; fi
COPY backend/datasentinel ./datasentinel
COPY --from=frontend /app/frontend/dist ./static
RUN useradd --uid 10001 --create-home datasentinel \
    && mkdir -p /data && chown datasentinel:datasentinel /data
USER datasentinel
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/v1/ready', timeout=4)"
# exec keeps uvicorn as PID 1 (receives SIGTERM); sh -c lets platforms such as Render set $PORT.
CMD ["sh", "-c", "exec uvicorn datasentinel.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*"]
