#!/bin/sh
set -e

echo "[tracking-service] aplicando migraciones..."
alembic upgrade head

# Servicio de alto caudal: varios workers de uvicorn en el mismo contenedor.
WORKERS="${UVICORN_WORKERS:-2}"
echo "[tracking-service] arrancando API en :8002 con ${WORKERS} worker(s)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers "${WORKERS}" \
    --proxy-headers --no-access-log
